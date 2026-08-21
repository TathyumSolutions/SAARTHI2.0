#import queue

#class StepStreamManager:
#    def __init__(self):
#        # Dictionary storing a list of active queues for each session_id
#        self.session_queues = {}

#    def listen(self, session_id):
#        """Called by the SSE route to start listening for updates on a session"""
#        q = queue.Queue()
#        session_id = str(session_id)
#        if session_id not in self.session_queues:
#            self.session_queues[session_id] = []
#        self.session_queues[session_id].append(q)
#        return q

#    def stop_listening(self, session_id, q):
#        """Cleans up the queue from memory when the browser disconnects"""
#        session_id = str(session_id)
#        if session_id in self.session_queues:
#            if q in self.session_queues[session_id]:
#                self.session_queues[session_id].remove(q)
#            if not self.session_queues[session_id]:
#                del self.session_queues[session_id]

#    def push_step(self, session_id, step_text, is_sql):
#        """Called inside your RAG/SQL code to stream a step to the frontend"""
#        session_id = str(session_id)
#        if session_id in self.session_queues:
#            for q in self.session_queues[session_id]:
#                q.put({"step": step_text, "is_sql": is_sql})

# Global single instance to share across your app modules
#stream_manager = StepStreamManager()


import queue

class StepStreamManager:
    def __init__(self):
        # Dictionary storing active listener queues for each session_id
        self.session_queues = {}
        # Buffer to store step history so late connections don't miss steps
        self.session_history = {}
        # How many independent tracks (router tool calls) are still expected
        # to report "DONE" for the current question - see begin_tracks().
        self.pending_tracks = {}

    def start_new_query(self, session_id):
        """Call this at the start of every new question, so old steps don't leak into the new answer."""
        session_id = str(session_id)
        self.session_history[session_id] = []
        self.pending_tracks[session_id] = 1

    def begin_tracks(self, session_id, count):
        """Call this once a question has been split into `count` independent
        tracks (e.g. router tool calls dispatched in parallel), so a single
        track finishing early doesn't end the whole Chain of Thought stream
        while the others are still mid-flight. Each track still pushes its
        own "DONE" the way it always has - only the last one actually
        reaches the frontend; earlier ones are swallowed by push_step."""
        session_id = str(session_id)
        self.pending_tracks[session_id] = max(1, int(count))

    def listen(self, session_id):
        """Called by the SSE route to start listening for updates on a session"""
        session_id = str(session_id)
        q = queue.Queue()
        
        if session_id not in self.session_queues:
            self.session_queues[session_id] = []
        self.session_queues[session_id].append(q)

        # If steps were generated before the browser connected, flush them out immediately
        if session_id in self.session_history:
            for past_step in self.session_history[session_id]:
                q.put(past_step)

        return q

    def stop_listening(self, session_id, q):
        """Cleans up the queue from memory when the browser disconnects"""
        session_id = str(session_id)
        if session_id in self.session_queues:
            if q in self.session_queues[session_id]:
                self.session_queues[session_id].remove(q)
            if not self.session_queues[session_id]:
                del self.session_queues[session_id]
                # Clear history once the session completes and disconnects
                if session_id in self.session_history:
                    del self.session_history[session_id]

    #def push_step(self, session_id, step_text, is_sql):
    #    """Called inside your RAG/SQL code to stream a step to the frontend"""
    #    session_id = str(session_id)
    #    payload = {"step": step_text, "is_sql": is_sql}
        
        # Save to history buffer first
    #    if session_id not in self.session_history:
    #        self.session_history[session_id] = []
    #    self.session_history[session_id].append(payload)

        # Stream real-time to active listeners
    #    if session_id in self.session_queues:
    #        for q in self.session_queues[session_id]:
    #            q.put(payload)

    def push_step(self, session_id, step_data, is_sql=False):

        session_id = str(session_id)

        # Multiple tracks can be running this question concurrently (see
        # begin_tracks). Each one calls push_step(..., "DONE", ...) on its
        # own completion, but the Chain of Thought is only actually done
        # once every expected track has reported in - otherwise the first
        # track to finish would close the SSE stream and freeze every
        # other track's in-flight steps at "Processing..." forever.
        if step_data == "DONE":
            remaining = self.pending_tracks.get(session_id, 1) - 1
            self.pending_tracks[session_id] = remaining
            if remaining > 0:
                return

        payload = {
            "step": step_data,
            "is_sql": is_sql
        }

    # Store in history buffer
        if session_id not in self.session_history:
            self.session_history[session_id] = []

        self.session_history[session_id].append(payload)

    # Stream live to active listeners
        if session_id in self.session_queues:
            for q in self.session_queues[session_id]:
                q.put(payload)            

# Global single instance to share across your app modules
stream_manager = StepStreamManager()