/**
 * "Configure AI Model" modal on /index: add and edit model configurations.
 *
 * - Picking a provider (or switching to Open Source) fills in that
 *   provider's default API endpoint, unless the user typed their own URL.
 * - openModelEditor(null)   -> add mode
 *   openModelEditor(config) -> edit mode for an existing DB configuration
 *
 * Cloud endpoints are OpenAI-compatible *base* URLs: the backend hands
 * them to ChatOpenAI(openai_api_base=...), which appends /chat/completions
 * itself. The Ollama endpoint is the full chat URL the backend POSTs to.
 *
 * Fires `saarthi:models-changed` on document after a successful save.
 */
(function () {
    'use strict';

    const OLLAMA_DEFAULT_ENDPOINT = 'http://ollama:11434/api/chat';

    const PROVIDER_DEFAULT_ENDPOINTS = Object.freeze({
        'Anthropic': 'https://api.anthropic.com/v1/',
        'OpenAI': 'https://api.openai.com/v1',
        'Google': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'Meta': 'https://api.llama.com/compat/v1/',
        'Mistral AI': 'https://api.mistral.ai/v1',
        'Cohere': 'https://api.cohere.ai/compatibility/v1',
        'Hugging Face': 'https://router.huggingface.co/v1',
        'Custom Provider': ''
    });

    // Any of these in the endpoint field counts as "not typed by the user",
    // so changing provider/type may replace it.
    const KNOWN_DEFAULT_ENDPOINTS = new Set([
        OLLAMA_DEFAULT_ENDPOINT,
        'http://ollama:11434/api/generate',
        ...Object.values(PROVIDER_DEFAULT_ENDPOINTS).filter(Boolean)
    ]);

    // Same bounds as GET /api/model-config/parameters.
    const DEFAULT_MAX_TOKENS = 4096;
    const DEFAULT_TEMPERATURE = 0.7;
    const MAX_TOKENS_RANGE = Object.freeze({ min: 1, max: 128000 });
    const TEMPERATURE_RANGE = Object.freeze({ min: 0, max: 2 });

    let editingConfig = null;

    const el = function (id) { return document.getElementById(id); };

    function isOpenSourceSelected() {
        const radio = el('openSource');
        return Boolean(radio && radio.checked);
    }

    function defaultEndpointFor(provider, openSource) {
        if (openSource) return OLLAMA_DEFAULT_ENDPOINT;
        return PROVIDER_DEFAULT_ENDPOINTS[provider] || '';
    }

    function isAutofillable(value) {
        const trimmed = String(value || '').trim();
        return !trimmed || KNOWN_DEFAULT_ENDPOINTS.has(trimmed);
    }

    function applyDefaultEndpoint() {
        const endpoint = el('modalEndpointUrl');
        const provider = el('modalProviderSelect');
        if (!endpoint || !provider) return;
        if (endpoint.dataset.userEdited === '1' && !isAutofillable(endpoint.value)) return;
        endpoint.value = defaultEndpointFor(provider.value, isOpenSourceSelected());
        endpoint.dataset.userEdited = '0';
    }

    function setModalMode(isEdit) {
        const title = el('modelModalTitle');
        const saveBtn = el('modelModalSaveBtn');
        const apiKey = el('modalApiKey');
        if (title) title.textContent = isEdit ? 'Edit AI Model' : 'Configure New AI Model';
        if (saveBtn) saveBtn.textContent = isEdit ? 'Update Configuration' : 'Save Configuration';
        if (apiKey) apiKey.placeholder = isEdit ? 'Leave blank to keep the current key' : 'sk-...';
    }

    function showModal() {
        const modal = el('modelModal');
        if (!modal) return;
        modal.classList.add('active');
        modal.style.display = 'flex';
    }

    function resetForm() {
        el('standardApi').checked = true;
        el('modalProviderSelect').selectedIndex = 0;
        el('modalModelName').value = '';
        el('modalModelId').value = '';
        el('modalModelId').dataset.userEdited = '0';
        el('modalApiKey').value = '';
        el('modalEndpointUrl').value = '';
        el('modalEndpointUrl').dataset.userEdited = '0';
        el('modalMaxTokens').value = String(DEFAULT_MAX_TOKENS);
        el('modalTemperature').value = String(DEFAULT_TEMPERATURE);
        el('modalDescription').value = '';
    }

    /** Parsed generation settings, or {error} when a value is out of range. */
    function readGenerationSettings() {
        const maxTokensRaw = el('modalMaxTokens').value.trim();
        const temperatureRaw = el('modalTemperature').value.trim();
        const maxTokens = maxTokensRaw === '' ? DEFAULT_MAX_TOKENS : Number(maxTokensRaw);
        const temperature = temperatureRaw === '' ? DEFAULT_TEMPERATURE : Number(temperatureRaw);

        if (!Number.isInteger(maxTokens) || maxTokens < MAX_TOKENS_RANGE.min || maxTokens > MAX_TOKENS_RANGE.max) {
            return { error: `Max Tokens must be a whole number between ${MAX_TOKENS_RANGE.min} and ${MAX_TOKENS_RANGE.max}.` };
        }
        if (!Number.isFinite(temperature) || temperature < TEMPERATURE_RANGE.min || temperature > TEMPERATURE_RANGE.max) {
            return { error: `Temperature must be between ${TEMPERATURE_RANGE.min} and ${TEMPERATURE_RANGE.max}.` };
        }
        return {
            max_tokens: maxTokens,
            temperature: temperature,
            description: el('modalDescription').value.trim() || null
        };
    }

    function fillForm(config) {
        const settings = config.settings || {};
        const openSource = config.provider === 'ollama' || String(config.model || '').startsWith('ollama://');
        el(openSource ? 'openSource' : 'standardApi').checked = true;

        const providerSelect = el('modalProviderSelect');
        const providerLabel = settings.provider_label || config.provider;
        const match = Array.from(providerSelect.options).find(function (opt) {
            return opt.value.toLowerCase() === String(providerLabel || '').toLowerCase();
        });
        providerSelect.value = match ? match.value : 'Custom Provider';

        el('modalModelName').value = config.name || '';
        el('modalModelId').value = bareModelId(config.model);
        el('modalModelId').dataset.userEdited = '1';
        el('modalApiKey').value = '';

        const endpoint = el('modalEndpointUrl');
        endpoint.value = settings.base_url || '';
        endpoint.dataset.userEdited = isAutofillable(endpoint.value) ? '0' : '1';
        if (!endpoint.value) applyDefaultEndpoint();

        if (settings.max_tokens != null) el('modalMaxTokens').value = String(settings.max_tokens);
        if (settings.temperature != null) el('modalTemperature').value = String(settings.temperature);
        el('modalDescription').value = settings.description || '';
    }

    function openModelEditor(config) {
        editingConfig = config || null;
        resetForm();
        if (editingConfig) {
            fillForm(editingConfig);
        } else {
            applyDefaultEndpoint();
        }
        setModalMode(Boolean(editingConfig));
        refreshModelIdHelp();
        showModal();
    }

    function bareModelId(model) {
        return String(model || '').trim().replace(/^(ollama|api):\/\//, '');
    }

    function slugFromName(name) {
        return String(name || '').trim().toLowerCase().replace(/\s+/g, '-');
    }

    function modelPrefix(isStandard, endpointUrl) {
        const looksLikeOllama = endpointUrl.toLowerCase().includes('ollama');
        return (!isStandard && (!endpointUrl || looksLikeOllama)) ? 'ollama' : 'api';
    }

    // Open Source: offer the models Ollama actually has, so an id like
    // "llama-2-7b" (which Ollama does not know) is not saved by accident.
    function refreshModelIdHelp() {
        const help = el('modalModelIdHelp');
        const options = el('ollamaModelOptions');
        if (!help || !options) return;
        options.innerHTML = '';
        if (!isOpenSourceSelected()) {
            help.textContent = 'Exact identifier the provider expects';
            return;
        }
        help.textContent = 'Checking which models Ollama has installed...';
        authFetch('/api/model-config/ollama-models')
            .then(function (response) { return response.ok ? response.json() : { reachable: false, models: [] }; })
            .then(function (data) {
                if (!isOpenSourceSelected()) return;
                (data.models || []).forEach(function (name) {
                    const option = document.createElement('option');
                    option.value = name;
                    options.appendChild(option);
                });
                if (!data.reachable) {
                    help.textContent = 'Ollama is not reachable right now - check that the ollama container is running.';
                } else if (!(data.models || []).length) {
                    help.textContent = 'Ollama has no models installed yet (pull one, e.g. llama2:7b).';
                } else {
                    help.textContent = `Installed in Ollama: ${data.models.join(', ')}`;
                }
            })
            .catch(function () {
                help.textContent = 'Could not check the models installed in Ollama.';
            });
    }

    function saveModel() {
        const modelName = el('modalModelName').value.trim();
        const apiKey = el('modalApiKey').value.trim();
        const endpointUrl = (el('modalEndpointUrl').value || '').trim();
        const isStandard = el('standardApi').checked;
        const providerLabel = el('modalProviderSelect').value || 'Custom Provider';

        if (!modelName) {
            alert('Please provide a Model Name!');
            return;
        }

        const bareId = bareModelId(el('modalModelId').value) || slugFromName(modelName);
        if (/\s/.test(bareId)) {
            alert('Model ID cannot contain spaces - use the exact identifier, e.g. "gpt-4o" or "llama2:7b".');
            return;
        }

        const generation = readGenerationSettings();
        if (generation.error) {
            alert(generation.error);
            return;
        }

        // The id comes from the Model ID field, never from the display
        // name ("ollama://llama2:7b" cannot be derived from "Llama 2 7B").
        const prefix = modelPrefix(isStandard, endpointUrl);
        const modelId = `${prefix}://${bareId}`;

        const settings = {
            base_url: endpointUrl || null,
            model_engine: prefix === 'ollama' ? 'ollama' : 'openai_compatible',
            provider_label: providerLabel,
            max_tokens: generation.max_tokens,
            temperature: generation.temperature,
            description: generation.description
        };
        // On edit a blank key means "keep the stored one" (the backend merges settings).
        if (apiKey || !editingConfig) settings.custom_key = apiKey || null;

        const payload = {
            name: modelName,
            model: modelId,
            provider: prefix === 'ollama' ? 'ollama' : providerLabel,
            settings: settings
        };

        const isEdit = Boolean(editingConfig);
        const url = isEdit
            ? `/api/model-config/configurations/${encodeURIComponent(editingConfig.id)}`
            : '/api/model-config/configurations';

        authFetch(url, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (response) {
                return response.json().catch(function () { return null; }).then(function (body) {
                    if (!response.ok) {
                        throw new Error((body && body.error) || `Request rejected with status code: ${response.status}`);
                    }
                    return body;
                });
            })
            .then(function (body) {
                const saved = (body && body.configuration) || payload;
                if (typeof closeModal === 'function') closeModal('modelModal');
                editingConfig = null;
                resetForm();
                document.dispatchEvent(new CustomEvent('saarthi:models-changed', {
                    detail: { action: isEdit ? 'updated' : 'created', config: saved }
                }));
                alert(`Model "${modelName}" ${isEdit ? 'updated' : 'configured and activated'} successfully!`);
            })
            .catch(function (error) {
                console.error('Error saving model configuration:', error);
                alert(`Failed to save model: ${error.message}`);
            });
    }

    document.addEventListener('DOMContentLoaded', function () {
        const providerSelect = el('modalProviderSelect');
        const endpoint = el('modalEndpointUrl');
        if (providerSelect) providerSelect.addEventListener('change', applyDefaultEndpoint);
        document.querySelectorAll('input[name="modelType"]').forEach(function (radio) {
            radio.addEventListener('change', applyDefaultEndpoint);
            radio.addEventListener('change', refreshModelIdHelp);
        });

        // Until the user types their own Model ID, suggest one from the name.
        const nameInput = el('modalModelName');
        const idInput = el('modalModelId');
        if (nameInput && idInput) {
            nameInput.addEventListener('input', function () {
                if (idInput.dataset.userEdited !== '1') idInput.value = slugFromName(nameInput.value);
            });
            idInput.addEventListener('input', function () {
                idInput.dataset.userEdited = idInput.value.trim() ? '1' : '0';
            });
        }
        if (endpoint) {
            endpoint.addEventListener('input', function () {
                endpoint.dataset.userEdited = isAutofillable(endpoint.value) ? '0' : '1';
            });
        }
    });

    window.openModelEditor = openModelEditor;
    window.saveModel = saveModel;
})();
