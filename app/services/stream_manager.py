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