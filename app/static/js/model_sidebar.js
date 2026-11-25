/**
 * Configured Models sidebar (shared by every page that extends base.html).
 *
 * - One list per model: a DB configuration ("ollama://llama2:7b") and its
 *   registry entry ("llama2:7b") are the same model, so they are merged on
 *   the bare id. The configuration wins because it is editable and carries
 *   the endpoint/key settings.
 * - Configured (DB) models get Edit / Delete actions. Registry-only models
 *   are the built-in catalog and have no actions.
 *
 * Exposes on window:
 *   normalizeModelId(value)                -> bare model id
 *   renderConfiguredModelsSidebar(configs, registryModels)
 *   loadConfiguredModelsSidebar()          -> Promise
 * Fires `saarthi:models-changed` on document after a delete.
 */
(function () {
    'use strict';

    function normalizeModelId(value) {
        return String(value || '').trim().replace(/^(ollama|api):\/\//, '').toLowerCase();
    }

    function makeActionButton(icon, title, onClick) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'model-action-btn';
        btn.title = title;
        btn.setAttribute('aria-label', title);
        btn.textContent = icon;
        btn.addEventListener('click', function (event) {
            event.stopPropagation();
            onClick();
        });
        return btn;
    }

    function editConfiguredModel(config) {
        if (typeof window.openModelEditor === 'function') {
            window.openModelEditor(config);
            return;
        }
        // The configure modal lives on /index only.
        window.location.href = `/index?edit_model=${encodeURIComponent(config.id)}`;
    }

    function deleteConfiguredModel(config) {
        const label = config.name || config.model;
        if (!window.confirm(`Delete the model configuration "${label}"?`)) return;

        authFetch(`/api/model-config/configurations/${encodeURIComponent(config.id)}`, { method: 'DELETE' })
            .then(function (response) {
                return response.json().catch(function () { return {}; }).then(function (body) {
                    if (!response.ok) throw new Error(body.error || `Delete failed (status ${response.status})`);
                    return body;
                });
            })
            .then(function () {
                const active = localStorage.getItem('saarthi_active_model');
                if (active && normalizeModelId(active) === normalizeModelId(config.model)) {
                    localStorage.removeItem('saarthi_active_model');
                }
                document.dispatchEvent(new CustomEvent('saarthi:models-changed', {
                    detail: { action: 'deleted', config: config }
                }));
            })
            .catch(function (error) {
                console.error('Error deleting model configuration:', error);
                alert(`Failed to delete model: ${error.message}`);
            });
    }

    function buildItem(label, title, marker, config) {
        const item = document.createElement('div');
        item.className = 'sub-item model-sub-item';
        item.title = title;

        const text = document.createElement('span');
        text.className = 'model-sub-item-label';
        text.textContent = `${marker} ${label}`;
        item.appendChild(text);

        if (config) {
            const actions = document.createElement('span');
            actions.className = 'model-sub-item-actions';
            actions.appendChild(makeActionButton('✎', 'Edit model', function () { editConfiguredModel(config); }));
            actions.appendChild(makeActionButton('🗑', 'Delete model', function () { deleteConfiguredModel(config); }));
            item.appendChild(actions);
        }
        return item;
    }

    /**
     * The one list of selectable models, shared by this sidebar and the chat
     * page's two dropdowns so they can never disagree. One entry per model:
     * a saved configuration wins over the registry entry for the same id
     * (it is editable and carries the endpoint/key). Open-source registry
     * models use the "ollama://<name>" value every Ollama route expects.
     * Entries that share a display name get their model id appended, so two
     * different models are never shown under the same label.
     */
    function buildModelCatalog(configurations, registryModels) {
        const entries = [];
        const seen = new Set();
        const add = function (entry) {
            const key = normalizeModelId(entry.value);
            if (!key || seen.has(key)) return;
            seen.add(key);
            entries.push(entry);
        };

        (configurations || []).forEach(function (config) {
            const value = String(config.model || '');
            const isOpenSource = config.provider === 'ollama' || value.startsWith('ollama://');
            add({ value: value, label: config.name || value, openSource: isOpenSource, config: config });
        });
        (registryModels || []).forEach(function (model) {
            const isOpenSource = model.type === 'open_source';
            add({
                value: isOpenSource ? `ollama://${model.name}` : model.name,
                label: model.display_name || model.name,
                openSource: isOpenSource,
                config: null
            });
        });

        const labelCounts = {};
        entries.forEach(function (e) { labelCounts[e.label] = (labelCounts[e.label] || 0) + 1; });
        entries.forEach(function (e) {
            if (labelCounts[e.label] > 1) e.label = `${e.label} (${normalizeModelId(e.value)})`;
        });
        return entries;
    }

    // Flag open-source models Ollama does not have - they fail on every
    // question with "model not found".
    function markUninstalledModels(wrapper) {
        authFetch('/api/model-config/ollama-models')
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (!data || !data.reachable) return;
                const installed = new Set((data.models || []).map(function (m) { return String(m).toLowerCase(); }));
                wrapper.querySelectorAll('.model-sub-item[data-open-source="1"]').forEach(function (item) {
                    const id = item.dataset.modelId;
                    const ok = installed.has(id) || (!id.includes(':') && installed.has(`${id}:latest`));
                    if (ok) return;
                    item.classList.add('model-not-installed');
                    item.title = `${item.title} - not installed in Ollama`;
                    const label = item.querySelector('.model-sub-item-label');
                    if (label) label.textContent = `⚠ ${label.textContent.replace(/^\S+\s/, '')}`;
                });
            })
            .catch(function () { /* marker is best-effort */ });
    }

    function renderConfiguredModelsSidebar(configurations, registryModels) {
        const wrapper = document.getElementById('configuredModelsList');
        if (!wrapper) return;

        const plusBtn = document.getElementById('plusModelBtn');
        wrapper.innerHTML = '';
        const catalog = buildModelCatalog(configurations, registryModels);

        catalog.forEach(function (entry) {
            const item = buildItem(entry.label, entry.value, entry.config ? '✓' : '•', entry.config);
            item.dataset.modelId = normalizeModelId(entry.value);
            item.dataset.openSource = entry.openSource ? '1' : '0';
            wrapper.appendChild(item);
        });

        if (catalog.length === 0) {
            const emptyItem = document.createElement('div');
            emptyItem.className = 'sub-item';
            emptyItem.style.color = '#64748b';
            emptyItem.style.fontStyle = 'italic';
            emptyItem.style.pointerEvents = 'none';
            emptyItem.textContent = 'No configured models found';
            wrapper.appendChild(emptyItem);
        }

        if (plusBtn) wrapper.appendChild(plusBtn);
        if (catalog.some(function (e) { return e.openSource; })) markUninstalledModels(wrapper);
    }

    function loadConfiguredModelsSidebar() {
        return Promise.all([
            authFetch('/api/model-config/configurations'),
            authFetch('/api/models/registry')
        ])
            .then(function (responses) {
                if (!responses[0].ok || !responses[1].ok) throw new Error('Could not load models');
                return Promise.all([responses[0].json(), responses[1].json()]);
            })
            .then(function (data) {
                renderConfiguredModelsSidebar(
                    (data[0] && data[0].configurations) || [],
                    (data[1] && data[1].models) || []
                );
            })
            .catch(function () {
                renderConfiguredModelsSidebar([], []);
            });
    }

    window.normalizeModelId = normalizeModelId;
    window.buildModelCatalog = buildModelCatalog;
    window.renderConfiguredModelsSidebar = renderConfiguredModelsSidebar;
    window.loadConfiguredModelsSidebar = loadConfiguredModelsSidebar;

    document.addEventListener('DOMContentLoaded', function () {
        const plusModelBtn = document.getElementById('plusModelBtn');
        if (plusModelBtn) {
            plusModelBtn.addEventListener('click', function () {
                if (typeof window.openModelEditor === 'function') {
                    window.openModelEditor(null);
                    return;
                }
                window.location.href = '/index?configure_model=1';
            });
        }

        // /index renders the sidebar itself together with its dropdowns.
        if (typeof window.loadSavedDatabaseModels !== 'function') {
            loadConfiguredModelsSidebar();
        }
    });

    // Pages without their own handler just refresh the sidebar.
    document.addEventListener('saarthi:models-changed', function () {
        if (typeof window.loadSavedDatabaseModels !== 'function') {
            loadConfiguredModelsSidebar();
        }
    });
})();
