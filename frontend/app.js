/**
 * CloudFormation Security Analyzer - Main Application
 * 
 * This file contains the main application logic for the static frontend.
 * It replaces Flask endpoints with API Gateway REST and WebSocket APIs.
 */

// Global state
let currentSessionId = null;
let currentResults = null;
let currentFilter = 'all';
let sseReceivedTerminalEvent = false;
let websocket = null;
let reconnectAttempts = 0;
let elapsedTimerInterval = null;
let elapsedSeconds = 0;
let renderedPropertyNames = new Set();

// DOM elements
const analysisForm = document.getElementById('analysisForm');
const urlInput = document.getElementById('urlInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const progressSection = document.getElementById('progressSection');
const resultsSection = document.getElementById('resultsSection');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const progressPercent = document.getElementById('progressPercent');
const activityLog = document.getElementById('activityLog');

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    hideAllSections();
});

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Form submission
    analysisForm.addEventListener('submit', handleFormSubmit);
    
    // Example URL buttons
    document.querySelectorAll('.example-url').forEach(btn => {
        btn.addEventListener('click', function() {
            urlInput.value = this.dataset.url;
        });
    });
}

/**
 * Hide all sections
 */
function hideAllSections() {
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
}

/**
 * Hide progress section and restore form state.
 * Called on analysis completion (success or failure) for both quick scan and detailed analysis.
 */
function hideProgressSection() {
    progressSection.classList.add('hidden');
    progressSection.classList.remove('pulse-bg');
    if (typeof stopElapsedTimer === 'function') stopElapsedTimer();
    if (typeof stopMessageRotator === 'function') stopMessageRotator();
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = '<i class="fas fa-search mr-2"></i>Start Security Analysis';
}

// Rotating status messages for quick scan
const QUICK_SCAN_MESSAGES = [
    "Connecting to security agent...",
    "Analyzing resource properties...",
    "Evaluating security configurations...",
    "Checking compliance requirements...",
    "Assessing risk levels..."
];

let messageRotatorInterval = null;
let messageIndex = 0;

/**
 * Start cycling through status messages every 3 seconds during quick scan
 */
function startMessageRotator() {
    messageIndex = 0;
    progressText.textContent = QUICK_SCAN_MESSAGES[messageIndex];
    messageRotatorInterval = setInterval(() => {
        messageIndex = (messageIndex + 1) % QUICK_SCAN_MESSAGES.length;
        progressText.textContent = QUICK_SCAN_MESSAGES[messageIndex];
    }, 3000);
}

/**
 * Stop the message rotator
 */
function stopMessageRotator() {
    if (messageRotatorInterval) {
        clearInterval(messageRotatorInterval);
        messageRotatorInterval = null;
    }
}

/**
 * Start the elapsed timer, updating every second with format "Elapsed: Xs"
 */
function startElapsedTimer() {
    stopElapsedTimer();
    elapsedSeconds = 0;
    updateElapsedDisplay();
    elapsedTimerInterval = setInterval(() => {
        elapsedSeconds++;
        updateElapsedDisplay();
    }, 1000);
}

/**
 * Stop the elapsed timer
 */
function stopElapsedTimer() {
    if (elapsedTimerInterval) {
        clearInterval(elapsedTimerInterval);
        elapsedTimerInterval = null;
    }
}

/**
 * Update the elapsed timer display element
 */
function updateElapsedDisplay() {
    const el = document.getElementById('elapsedTimer');
    if (el) {
        el.textContent = `Elapsed: ${elapsedSeconds}s`;
    }
}

/**
 * Handle form submission
 */
function handleFormSubmit(e) {
    e.preventDefault();
    const url = urlInput.value.trim();
    
    if (!url) {
        showError('Please enter a valid URL');
        return;
    }
    
    const analysisType = document.querySelector('input[name="analysisType"]:checked').value;
    startAnalysis(url, analysisType);
}

/**
 * Start analysis
 */
async function startAnalysis(url, analysisType = 'quick') {
    // Reset UI state: hide all sections and clear previous results
    hideAllSections();
    resultsSection.innerHTML = '';
    renderedPropertyNames.clear();
    progressSection.classList.remove('hidden');
    
    // Start elapsed timer
    startElapsedTimer();
    
    // Disable submit button
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = '<div class="spinner mr-2"></div>Analyzing...';
    
    // Reset progress
    updateProgress(0, 'Starting analysis...');
    clearActivityLog();
    
    // For quick scans, use SSE streaming for real-time property results
    if (analysisType === 'quick') {
        await startQuickScanSSE(url);
        return;
    }

    // Detailed analysis: use WebSocket + REST flow
    try {
        // Establish WebSocket connection first
        await connectWebSocket();
        
        // Start analysis via REST API
        const response = await fetch(`${CONFIG.API_BASE_URL}/analysis`, {
            method: 'POST',
            headers: getAuthHeaders({
                'Content-Type': 'application/json'
            }),
            body: JSON.stringify({ 
                resourceUrl: url,
                analysisType: analysisType
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.error) {
            showError(data.error);
            return;
        }
        
        currentSessionId = data.analysisId;
        
        // Subscribe to WebSocket updates for detailed analysis
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify({
                action: 'subscribe',
                analysisId: currentSessionId
            }));
        }
        
        addActivityLogEntry('🚀 Analysis Started', 'Initializing security analysis', 'info');
        
    } catch (error) {
        console.error('Error:', error);
        showError('Failed to start analysis: ' + error.message);
        
        // Re-enable form
        analyzeBtn.disabled = false;
        analyzeBtn.innerHTML = '<i class="fas fa-search mr-2"></i>Start Security Analysis';
    }
}

/**
 * Connect to WebSocket API
 */
function connectWebSocket() {
    return new Promise((resolve, reject) => {
        try {
            // Close existing connection if any
            if (websocket) {
                websocket.close();
            }
            
            // Create new WebSocket connection
            websocket = new WebSocket(CONFIG.WEBSOCKET_URL);
            
            // Connection opened
            websocket.onopen = function(event) {
                console.log('WebSocket connected');
                reconnectAttempts = 0;
                resolve();
            };
            
            // Listen for messages
            websocket.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    handleWebSocketMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };
            
            // Connection closed
            websocket.onclose = function(event) {
                console.log('WebSocket disconnected');
                
                // Attempt to reconnect if not intentional
                if (reconnectAttempts < CONFIG.TIMEOUTS.maxReconnectAttempts) {
                    reconnectAttempts++;
                    console.log(`Reconnecting... Attempt ${reconnectAttempts}`);
                    setTimeout(() => connectWebSocket(), 2000 * reconnectAttempts);
                }
            };
            
            // Connection error
            websocket.onerror = function(error) {
                console.error('WebSocket error:', error);
                reject(error);
            };
            
            // Timeout if connection takes too long
            setTimeout(() => {
                if (websocket.readyState !== WebSocket.OPEN) {
                    reject(new Error('WebSocket connection timeout'));
                }
            }, CONFIG.TIMEOUTS.websocketTimeout);
            
        } catch (error) {
            reject(error);
        }
    });
}

/**
 * Handle WebSocket messages
 */
/**
 * Handle WebSocket messages
 */
function handleWebSocketMessage(data) {
    // Existing type/action routing (for forward compatibility)
    const messageType = data.type || data.action;
    if (messageType) {
        switch (messageType) {
            case 'progress': return handleProgressUpdate(data);
            case 'property_complete': return handlePropertyComplete(data);
            case 'analysis_complete': return handleAnalysisComplete(data);
            case 'error': return handleError(data);
        }
    }

    // Backend step-based messages from Step Functions workflow
    const step = data.step;
    if (step) {
        switch (step) {
            case 'crawl': return handleStepCrawlComplete(data);
            case 'property_analyzed': return handleStepPropertyAnalyzed(data);
            case 'analyze': return handleStepAnalyzeComplete(data);
            case 'complete': return handleStepWorkflowComplete(data);
            default:
                console.log('Unknown step:', step, data);
                return;
        }
    }

    console.log('Unrecognized WebSocket message:', data);
}


/**
 * Handle progress update
 */
function handleProgressUpdate(data) {
    const progress = data.progress || 0;
    const stepText = data.step || data.message || 'Processing...';
    
    updateProgress(progress, stepText);
    
    if (data.details) {
        addActivityLogEntry(stepText, data.details, 'info');
    }
}

/**
 * Handle property analysis complete
 */
function handlePropertyComplete(data) {
    const property = data.property || data.propertyResult;
    
    if (!property) {
        console.warn('Property complete message missing property data');
        return;
    }
    
    // Show results section if not already visible
    resultsSection.classList.remove('hidden');
    
    // Add property card to UI
    addPropertyCardToUI(property);
    
    // Update progress
    if (data.progress && data.total) {
        const percentage = Math.round((data.progress / data.total) * 100);
        updateProgress(percentage, `Analyzed ${property.name} (${data.progress}/${data.total})`);
    }
    
    // Add to activity log
    const riskIcon = getRiskIcon(property.risk_level);
    addActivityLogEntry(
        `${riskIcon} ${property.name}`,
        `${property.risk_level} risk - Analysis complete`,
        'success'
    );
}

/**
 * Handle analysis complete
 */
async function handleAnalysisComplete(data) {
    updateProgress(100, 'Analysis complete');
    addActivityLogEntry('✅ Analysis Complete', 'All properties analyzed successfully', 'success');
    
    // Fetch final results
    if (currentSessionId) {
        await fetchResults(currentSessionId);
    }
    
    hideProgressSection();
}

/**
 * Handle error
 */
function handleError(data) {
    const errorMessage = data.error || data.message || 'An error occurred';
    showError(errorMessage);
    addActivityLogEntry('❌ Error', errorMessage, 'error');
    hideProgressSection();
}

/**
 * Handle step-based crawl complete message from detailed analysis workflow.
 * Updates progress to ~20% and logs crawl completion.
 */
function handleStepCrawlComplete(data) {
    updateProgress(20, 'Documentation crawl completed');
    addActivityLogEntry(
        '📄 Crawl Complete',
        data.detail?.message || 'Documentation crawling is complete',
        'success'
    );
}

/**
 * Parse text that may contain numbered items (e.g., "1. Do X 2. Do Y") into
 * an HTML ordered list. Returns <ol> with <li> items when 2+ items are found,
 * a <span> with plain text for non-list content, or empty string for empty input.
 */
function parseNumberedList(text) {
    if (!text) return '';

    // Try "1. " format first, then "1) " format
    let items = text.split(/(?:^|\s)(?=\d+\.\s)/).filter(s => s.trim());
    let prefixRegex = /^\d+\.\s*/;

    if (items.length < 2) {
        // Try "1) " format (some agents use parentheses)
        items = text.split(/(?:^|[\s:])(?=\d+\)\s)/).filter(s => s.trim());
        prefixRegex = /^\d+\)\s*/;
    }

    if (items.length >= 2) {
        const listItems = items.map(item => {
            const cleaned = item.replace(prefixRegex, '').trim();
            return `<li>${cleaned}</li>`;
        });
        return `<ol class="list-decimal list-inside space-y-1 text-sm text-gray-700">${listItems.join('')}</ol>`;
    }

    return `<span>${text}</span>`;
}

/**
 * Normalize a property object from the Step Functions Map iteration output.
 * The Map output has: {property: {name, description}, propertyResult: {Payload: {...}}, index, totalProperties}
 * The analysis result (propertyResult.Payload) may contain the actual analysis or an error.
 * We merge the property metadata with the analysis result to produce a flat object
 * that createPropertyCard() can render.
 */
function normalizePropertyData(raw) {
    // If it already has a name and risk_level at top level, it's already normalized
    if (raw.name && raw.risk_level) return raw;

    // Extract property metadata (from crawler)
    const propMeta = raw.property || {};
    // Extract analysis result (from property analyzer Lambda)
    // In DynamoDB results: raw.propertyResult.Payload = {statusCode, resourceUrl, propertyName, result: "<text>"}
    // In WebSocket messages: raw.result = {statusCode, resourceUrl, propertyName, result: "<text>"}
    const analysisPayload = raw.propertyResult?.Payload || raw.result || raw.Payload || {};

    // The analysis result might be a parsed JSON object with analysis fields,
    // or it might be a raw text response that needs JSON extraction
    let analysis = {};
    if (typeof analysisPayload === 'string') {
        try {
            const jsonMatch = analysisPayload.match(/\{[\s\S]*\}/);
            if (jsonMatch) analysis = JSON.parse(jsonMatch[0]);
        } catch (e) { /* ignore */ }
    } else if (typeof analysisPayload === 'object' && !analysisPayload.error) {
        // The agent returns {statusCode, resourceUrl, propertyName, result: "<text with JSON>"}
        // Extract the JSON from the result field
        const resultText = analysisPayload.result || '';
        if (typeof resultText === 'string' && resultText.length > 0) {
            // Find balanced JSON object in the text by tracking brace depth
            const startIdx = resultText.indexOf('{');
            if (startIdx !== -1) {
                let depth = 0;
                let endIdx = -1;
                for (let i = startIdx; i < resultText.length; i++) {
                    if (resultText[i] === '{') depth++;
                    else if (resultText[i] === '}') {
                        depth--;
                        if (depth === 0) { endIdx = i; break; }
                    }
                }
                if (endIdx !== -1) {
                    try {
                        analysis = JSON.parse(resultText.substring(startIdx, endIdx + 1));
                    } catch (e) { /* ignore parse errors */ }
                }
            }
        } else if (typeof resultText === 'object') {
            analysis = resultText;
        }
    }

    return {
        name: analysis.propertyName || analysis.name || propMeta.name || raw.name || 'Unknown Property',
        risk_level: analysis.riskLevel || analysis.risk_level || propMeta.risk_level || 'MEDIUM',
        description: analysis.description || propMeta.description || '',
        security_impact: analysis.securityImplications || analysis.security_impact || analysis.securityImplication || propMeta.description || '',
        key_threat: analysis.key_threat || (analysis.commonMisconfigurations ? analysis.commonMisconfigurations[0] : '') || '',
        secure_configuration: analysis.secure_configuration || analysis.recommendations || analysis.recommendation || '',
        recommendation: analysis.recommendations || analysis.recommendation || analysis.secure_configuration || '',
        property_path: propMeta.name || raw.name || '',
        best_practices: analysis.bestPractices || [],
        common_misconfigurations: analysis.commonMisconfigurations || [],
    };
}

/**
 * Handle step-based property analyzed message from detailed analysis workflow.
 * Renders property card incrementally and updates progress proportionally between 20-90%.
 */
function handleStepPropertyAnalyzed(data) {
    const detail = data.detail || {};
    const index = detail.index || 0;
    const total = detail.total || 1;

    // Normalize the property data from the notification payload
    const property = normalizePropertyData(detail);

    // Calculate progress: scale between 20% (crawl done) and 90% (all properties done)
    const percent = Math.round(20 + ((index + 1) / total) * 70);
    updateProgress(percent, `Analyzing property ${index + 1} of ${total}`);

    // Track this property as already rendered via WebSocket
    if (property.name) {
        renderedPropertyNames.add(property.name);
    }

    // Show results section and render property card incrementally (no index — cards arrive out of order)
    resultsSection.classList.remove('hidden');
    addPropertyCardToUI(property);

    // Activity log
    const riskIcon = getRiskIcon(property.risk_level);
    addActivityLogEntry(
        `${riskIcon} ${property.name || 'Property'}`,
        `${property.risk_level || 'MEDIUM'} risk — property ${index + 1}/${total}`,
        'success'
    );
}

/**
 * Handle step-based analyze complete message from detailed analysis workflow.
 * Updates progress to ~90% indicating all property analysis is done.
 */
function handleStepAnalyzeComplete(data) {
    updateProgress(90, 'Property analysis completed');
    addActivityLogEntry(
        '🔍 Analysis Complete',
        data.detail?.message || 'All property analysis is complete',
        'success'
    );
}

/**
 * Handle step-based workflow complete message from detailed analysis workflow.
 * Updates progress to 100%, fetches final results, and resets the UI.
 */
async function handleStepWorkflowComplete(data) {
    updateProgress(100, 'Analysis complete');
    addActivityLogEntry(
        '✅ Workflow Complete',
        data.detail?.message || 'Detailed analysis workflow completed',
        'success'
    );

    // Fetch final results and display them
    if (currentSessionId) {
        await fetchResults(currentSessionId);
    }

    hideProgressSection();
}


/**
 * Fetch analysis results
 */
async function fetchResults(analysisId) {
    try {
        const response = await fetch(`${CONFIG.API_BASE_URL}/analysis/${analysisId}`, {
            method: 'GET',
            headers: getAuthHeaders()
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        currentResults = data;
        
        // Display results
        displayResults(currentResults);
        
    } catch (error) {
        console.error('Error fetching results:', error);
        showError('Failed to fetch results: ' + error.message);
    }
}

/**
 * Display quick scan results
 */
function displayQuickScanResults(results) {
    // Show results section
    resultsSection.classList.remove('hidden');
    
    // Parse the result string which contains JSON
    let properties = [];
    
    try {
        // The result field contains a text response with embedded JSON
        const resultText = results.result || '';
        
        // Extract JSON from the result text
        const jsonMatch = resultText.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
            const parsedResult = JSON.parse(jsonMatch[0]);
            properties = parsedResult.properties || [];
        }
    } catch (error) {
        console.error('Error parsing results:', error);
        showError('Failed to parse analysis results');
        return;
    }
    
    // Create results container
    resultsSection.innerHTML = `
        <div class="bg-white rounded-xl card-shadow p-8">
            <div class="flex items-center justify-between mb-6">
                <div>
                    <h3 class="text-2xl font-bold text-gray-800">Security Analysis Results</h3>
                    <p class="text-gray-600 mt-1">Found ${properties.length} security-critical properties</p>
                </div>
                <div class="text-sm text-gray-500">
                    <i class="fas fa-clock mr-1"></i>
                    ${new Date().toLocaleTimeString()}
                </div>
            </div>
            <div id="propertiesContainer" class="space-y-4"></div>
        </div>
    `;
    
    const container = document.getElementById('propertiesContainer');
    
    // Add each property card
    properties.forEach((property, index) => {
        const card = createPropertyCard({
            name: property.name,
            risk_level: property.riskLevel,
            security_impact: property.securityImplication,
            recommendation: property.recommendation
        }, index);
        card.classList.add('animate-fade-in');
        container.appendChild(card);
    });

    hideProgressSection();
}

/**
 * Display results
 */
function displayResults(results) {
    try {
        // Parse the results.S JSON string from the DynamoDB response
        let parsedResults;
        if (results.results && results.results.S) {
            parsedResults = JSON.parse(results.results.S);
        } else if (results.results && typeof results.results === 'string') {
            parsedResults = JSON.parse(results.results);
        } else if (results.results && results.results.properties) {
            parsedResults = results.results;
        } else {
            console.warn('No results.S field found in response:', results);
            showError('No analysis results found');
            analyzeBtn.disabled = false;
            analyzeBtn.innerHTML = '<i class="fas fa-search mr-2"></i>Start Security Analysis';
            return;
        }

        // Extract properties array — each element may be wrapped in a Payload key
        const rawProperties = parsedResults.properties || [];
        const properties = rawProperties.map(prop => {
            if (prop && prop.Payload) {
                return prop.Payload;
            }
            return prop;
        });

        // Show results section
        resultsSection.classList.remove('hidden');

        // Always rebuild the results container so cards appear in correct order
        // (incremental WebSocket rendering may have added cards out of order)
        resultsSection.innerHTML = `
            <div class="bg-white rounded-xl card-shadow p-8">
                <div class="flex items-center justify-between mb-6">
                    <div>
                        <h3 class="text-2xl font-bold text-gray-800">Security Analysis Results</h3>
                        <p class="text-gray-600 mt-1">Found ${properties.length} security-relevant properties</p>
                    </div>
                    <div class="text-sm text-gray-500">
                        <i class="fas fa-clock mr-1"></i>
                        ${new Date().toLocaleTimeString()}
                    </div>
                </div>
                <div id="propertiesContainer" class="space-y-4"></div>
            </div>
        `;
        let container = document.getElementById('propertiesContainer');

        // Render all property cards in order
        properties.forEach((property, index) => {
            const normalized = normalizePropertyData(property);
            const card = createPropertyCard(normalized, index);
            card.classList.add('animate-fade-in');
            container.appendChild(card);
        });

    } catch (error) {
        console.error('Error displaying results:', error);
        showError('Failed to display analysis results: ' + error.message);
    }

    // Re-enable form button and hide progress section
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = '<i class="fas fa-search mr-2"></i>Start Security Analysis';
    hideProgressSection();
}

/**
 * Add property card to UI
 */
function addPropertyCardToUI(property, index) {
    // Create results container if it doesn't exist
    let container = document.getElementById('propertiesContainer');
    if (!container) {
        resultsSection.innerHTML = `
            <div class="bg-white rounded-xl card-shadow p-8">
                <h3 class="text-2xl font-bold text-gray-800 mb-6">Security Analysis Results</h3>
                <div id="propertiesContainer" class="space-y-4"></div>
            </div>
        `;
        container = document.getElementById('propertiesContainer');
    }
    
    // Create property card
    const card = createPropertyCard(property, index);
    card.classList.add('animate-fade-in');
    container.appendChild(card);
}

/**
 * Create property card element
 */
function createPropertyCard(property, index) {
    const riskLevel = property.risk_level || 'MEDIUM';
    const riskClass = `risk-${riskLevel.toLowerCase()}`;
    const config = getRiskConfig(riskLevel);

    const card = document.createElement('div');
    card.className = `property-card bg-white rounded-xl card-shadow p-6 border border-gray-200 ${riskClass}`;

    // Build recommendation HTML using parseNumberedList
    const recommendationText = property.secure_configuration || property.recommendation;
    const recommendationHtml = recommendationText ? `
                <div>
                    <div class="text-sm font-semibold text-gray-800 mb-2">Recommendation</div>
                    <div class="text-sm text-gray-700 bg-green-50 border border-green-100 rounded-lg p-3">
                        <i class="fas fa-shield-alt text-green-600 mr-2"></i>
                        ${parseNumberedList(recommendationText)}
                    </div>
                </div>
            ` : '';

    // Title with optional index prefix
    const titlePrefix = typeof index === 'number' ? (index + 1) + '. ' : '';

    card.innerHTML = `
        <div class="flex items-start justify-between mb-4">
            <div class="flex items-start flex-1">
                <div class="bg-gray-50 rounded-lg p-2 mr-3">
                    <i class="${config.icon} text-lg" style="color: ${config.color};"></i>
                </div>
                <div class="flex-1">
                    <h4 class="text-lg font-bold text-gray-900">${titlePrefix}${property.name || 'Unknown Property'}</h4>
                    <div class="text-sm text-gray-500">${property.property_path || property.name || 'N/A'}</div>
                </div>
            </div>
            <div class="flex items-center space-x-3 ml-4">
                <div class="flex items-center px-3 py-1 rounded-full text-sm font-medium border"
                     style="background-color: ${config.bgColor}; border-color: ${config.color}20; color: ${config.color};">
                    <i class="${config.icon} mr-2" style="color: ${config.color};"></i>
                    ${riskLevel}
                </div>
            </div>
        </div>

        <div class="space-y-4">
            <div>
                <div class="text-sm font-semibold text-gray-800 mb-2">Security Impact</div>
                <div class="text-sm text-gray-700 leading-relaxed">${property.security_impact || property.securityImplication || 'No description available'}</div>
            </div>

            ${property.key_threat ? `
                <div>
                    <div class="text-sm font-semibold text-gray-800 mb-2">Key Threat</div>
                    <div class="text-sm text-gray-700 bg-red-50 border border-red-100 rounded-lg p-3">
                        <i class="fas fa-exclamation-triangle text-red-500 mr-2"></i>
                        ${property.key_threat}
                    </div>
                </div>
            ` : ''}

            ${recommendationHtml}
        </div>
    `;

    return card;
}

/**
 * Get risk configuration
 */
function getRiskConfig(riskLevel) {
    const configs = {
        'CRITICAL': { icon: 'fas fa-exclamation-triangle', color: '#dc2626', bgColor: '#fef2f2' },
        'HIGH': { icon: 'fas fa-exclamation-circle', color: '#ea580c', bgColor: '#fff7ed' },
        'MEDIUM': { icon: 'fas fa-info-circle', color: '#ca8a04', bgColor: '#fffbeb' },
        'LOW': { icon: 'fas fa-check-circle', color: '#16a34a', bgColor: '#f0fdf4' }
    };
    return configs[riskLevel] || configs['MEDIUM'];
}

/**
 * Get risk icon
 */
function getRiskIcon(riskLevel) {
    const icons = {
        'CRITICAL': '🔴',
        'HIGH': '🟠',
        'MEDIUM': '🟡',
        'LOW': '🟢'
    };
    return icons[riskLevel] || '⚪';
}

/**
 * Update progress
 */
function updateProgress(percent, text) {
    progressBar.style.width = percent + '%';
    progressPercent.textContent = percent + '%';
    progressText.textContent = text;
}

/**
 * Add activity log entry
 */
function addActivityLogEntry(title, details, type) {
    const entry = document.createElement('div');
    entry.className = `flex items-start p-3 bg-white rounded-lg border-l-4 ${
        type === 'success' ? 'border-green-500' : 
        type === 'error' ? 'border-red-500' : 'border-blue-500'
    }`;
    
    const icon = type === 'success' ? 'check-circle' : 
                type === 'error' ? 'exclamation-circle' : 'info-circle';
    const iconColor = type === 'success' ? 'text-green-500' : 
                     type === 'error' ? 'text-red-500' : 'text-blue-500';
    
    entry.innerHTML = `
        <i class="fas fa-${icon} ${iconColor} mt-1 mr-3"></i>
        <div class="flex-1">
            <div class="font-medium text-gray-800">${title}</div>
            ${details ? `<div class="text-sm text-gray-600">${details}</div>` : ''}
            <div class="text-xs text-gray-400">${new Date().toLocaleTimeString()}</div>
        </div>
    `;
    
    activityLog.appendChild(entry);
    activityLog.scrollTop = activityLog.scrollHeight;
}

/**
 * Clear activity log
 */
function clearActivityLog() {
    activityLog.innerHTML = '';
}

/**
 * Show error message
 */
function showError(message) {
    hideProgressSection();
    
    // Show error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4';
    errorDiv.innerHTML = `
        <div class="flex items-center">
            <i class="fas fa-exclamation-circle mr-2"></i>
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-auto">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    document.querySelector('.container').insertBefore(errorDiv, document.querySelector('.container').firstChild);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (errorDiv.parentNode) {
            errorDiv.remove();
        }
    }, 5000);
}

/**
 * Get authentication headers
 */
function getAuthHeaders(additionalHeaders = {}) {
    const headers = { ...additionalHeaders };
    
    // Add IAM authentication if configured
    if (CONFIG.AUTH.useIAM) {
        // IAM authentication would be handled by AWS SDK
        // This is a placeholder for the actual implementation
        console.warn('IAM authentication not yet implemented');
    }
    
    // Add Cognito authentication if configured
    if (CONFIG.AUTH.useCognito) {
        // Cognito authentication would be handled by AWS Amplify
        // This is a placeholder for the actual implementation
        const token = localStorage.getItem('cognitoToken');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
    }
    
    return headers;
}

/**
 * Parse SSE events from a text buffer.
 * Splits on double newlines to find complete event blocks, extracts event type and data fields,
 * and returns parsed events plus any remaining incomplete buffer.
 *
 * @param {string} buffer - Raw text buffer from the SSE stream
 * @returns {{ parsed: Array<{event: string, data: *}>, remaining: string }}
 */
function parseSSEEvents(buffer) {
    const events = [];
    const blocks = buffer.split('\n\n');
    // Last element may be an incomplete block
    const remaining = blocks.pop();

    for (const block of blocks) {
        if (!block.trim()) continue;
        let eventType = null;
        let data = null;
        for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) {
                eventType = line.slice(7);
            } else if (line.startsWith('data: ')) {
                try {
                    data = JSON.parse(line.slice(6));
                } catch (e) {
                    data = line.slice(6);
                }
            }
        }
        if (eventType) {
            events.push({ event: eventType, data });
        }
    }
    return { parsed: events, remaining: remaining || '' };
}

/**
 * Handle a single SSE event dispatched from the streaming quick scan.
 * Routes by event type: status, property, complete, error.
 *
 * @param {{ event: string, data: * }} sseEvent - Parsed SSE event
 */
function handleSSEEvent(sseEvent) {
    const { event, data } = sseEvent;

    switch (event) {
        case 'status':
            currentSessionId = data.analysisId;
            addActivityLogEntry('🚀 Analysis Started', 'Streaming security analysis in progress', 'info');
            break;

        case 'property': {
            // Show results section on first property
            resultsSection.classList.remove('hidden');

            // Ensure results container exists
            let container = document.getElementById('propertiesContainer');
            if (!container) {
                resultsSection.innerHTML = `
                    <div class="bg-white rounded-xl card-shadow p-8">
                        <div class="flex items-center justify-between mb-6">
                            <div>
                                <h3 class="text-2xl font-bold text-gray-800">Security Analysis Results</h3>
                                <p class="text-gray-600 mt-1" id="resultsSubtitle">Streaming results...</p>
                            </div>
                            <div class="text-sm text-gray-500">
                                <i class="fas fa-clock mr-1"></i>
                                ${new Date().toLocaleTimeString()}
                            </div>
                        </div>
                        <div id="propertiesContainer" class="space-y-4"></div>
                    </div>
                `;
                container = document.getElementById('propertiesContainer');
            }

            // Render property card using existing createPropertyCard
            const card = createPropertyCard({
                name: data.name,
                risk_level: data.riskLevel,
                security_impact: data.securityImplication,
                recommendation: data.recommendation
            }, data.index);
            card.classList.add('animate-fade-in');
            container.appendChild(card);

            // Update progress bar
            const percent = Math.round(((data.index + 1) / data.total) * 100);
            updateProgress(percent, `Analyzed ${data.name} (${data.index + 1}/${data.total})`);

            // Activity log
            const riskIcon = getRiskIcon(data.riskLevel);
            addActivityLogEntry(
                `${riskIcon} ${data.name}`,
                `${data.riskLevel} risk`,
                'success'
            );
            break;
        }

        case 'complete':
            sseReceivedTerminalEvent = true;
            hideProgressSection();
            addActivityLogEntry('✅ Analysis Complete', `Found ${data.totalProperties} security properties`, 'success');

            // Update subtitle if present
            const subtitle = document.getElementById('resultsSubtitle');
            if (subtitle) {
                subtitle.textContent = `Found ${data.totalProperties} security-critical properties`;
            }
            break;

        case 'error':
            sseReceivedTerminalEvent = true;
            showError(data.message || 'Analysis failed');
            hideProgressSection();
            break;

        default:
            console.warn('Unknown SSE event type:', event, data);
    }
}

/**
 * Start a quick scan using SSE streaming.
 * Uses fetch with a readable stream to parse SSE events as they arrive,
 * rendering property cards incrementally.
 *
 * @param {string} url - The CloudFormation resource URL to analyze
 */
async function startQuickScanSSE(url) {
    sseReceivedTerminalEvent = false;

    // Apply pulsing animation and start rotating status messages
    progressSection.classList.add('pulse-bg');
    startMessageRotator();

    try {
        const response = await fetch(`${CONFIG.API_BASE_URL}/analysis/stream`, {
            method: 'POST',
            headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ resourceUrl: url, analysisType: 'quick' })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const events = parseSSEEvents(buffer);
            buffer = events.remaining;

            for (const event of events.parsed) {
                handleSSEEvent(event);
            }
        }

        // If stream ended without a terminal event, fall back to polling
        if (!sseReceivedTerminalEvent && currentSessionId) {
            startFallbackPolling(currentSessionId);
        }
    } catch (error) {
        console.error('SSE stream error:', error);
        // If we already got a terminal event, the error is just the stream closing — ignore it
        if (!sseReceivedTerminalEvent) {
            // If we have an analysisId, the stream started but the connection dropped — poll for results
            if (currentSessionId) {
                startFallbackPolling(currentSessionId);
            } else {
                // No analysisId means the stream never started — show the error directly
                showError('Failed to start analysis: ' + error.message);
                hideProgressSection();
            }
        }
    }
}

/**
 * Fallback polling for when the SSE connection drops before receiving
 * a terminal event (complete or error). Polls GET /analysis/{analysisId}
 * every 2 seconds until the status is COMPLETED or FAILED.
 *
 * @param {string} analysisId - The analysis ID to poll for
 */
function startFallbackPolling(analysisId) {
    addActivityLogEntry('⚠️ Connection interrupted', 'Checking for results...', 'info');

    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(
                `${CONFIG.API_BASE_URL}/analysis/${analysisId}`,
                { headers: getAuthHeaders() }
            );

            if (!response.ok) {
                console.warn('Fallback poll returned status:', response.status);
                return; // Keep polling on non-OK responses
            }

            const data = await response.json();

            if (data.status === 'COMPLETED') {
                clearInterval(pollInterval);
                displayQuickScanResults(data.results);
                hideProgressSection();
            } else if (data.status === 'FAILED') {
                clearInterval(pollInterval);
                showError(data.error || 'Analysis failed');
                hideProgressSection();
            }
        } catch (error) {
            console.warn('Fallback poll network error:', error.message);
            // Keep polling — transient network errors shouldn't stop us
        }
    }, 2000);
}

/**
 * Cleanup on page unload
 */
window.addEventListener('beforeunload', function() {
    if (websocket) {
        websocket.close();
    }
});

// Expose functions for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { parseNumberedList, createPropertyCard };
} else if (typeof window !== 'undefined') {
    window.parseNumberedList = parseNumberedList;
    window.createPropertyCard = createPropertyCard;
}
