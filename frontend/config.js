/**
 * CloudFormation Security Analyzer - Configuration
 * 
 * BACKEND TOGGLE: Set USE_EKS to true for the new EKS backend,
 * or false to fallback to the legacy API Gateway + Lambda backend.
 */

const USE_EKS = true;  // Toggle: true = EKS (new), false = API Gateway (legacy fallback)

// EKS backend endpoints (new)
const EKS_ENDPOINTS = {
    API_BASE_URL: 'https://cfn-analyzer.YOUR_DOMAIN',
    WEBSOCKET_URL: 'wss://cfn-analyzer.YOUR_DOMAIN/ws',
};

// Legacy API Gateway endpoints (fallback — DO NOT DELETE)
const LEGACY_ENDPOINTS = {
    API_BASE_URL: 'https://YOUR_REST_API_ID.execute-api.us-east-1.amazonaws.com/dev',
    WEBSOCKET_URL: 'wss://YOUR_WS_API_ID.execute-api.us-east-1.amazonaws.com/dev',
};

const ACTIVE = USE_EKS ? EKS_ENDPOINTS : LEGACY_ENDPOINTS;

const CONFIG = {
    API_BASE_URL: window.location.hostname === 'localhost'
        ? 'http://localhost:8000'
        : ACTIVE.API_BASE_URL,
    
    WEBSOCKET_URL: window.location.hostname === 'localhost'
        ? 'ws://localhost:8000/ws'
        : ACTIVE.WEBSOCKET_URL,
    
    // Authentication configuration
    AUTH: {
        // Set to true if using AWS IAM authentication
        useIAM: false,
        
        // Set to true if using AWS Cognito
        useCognito: false,
        
        // Cognito configuration (if useCognito is true)
        cognito: {
            userPoolId: 'YOUR_USER_POOL_ID',
            clientId: 'YOUR_CLIENT_ID',
            region: 'YOUR_REGION'
        }
    },
    
    // Feature flags
    FEATURES: {
        // Enable batch analysis
        batchAnalysis: true,
        
        // Enable PDF report generation
        pdfReports: true,
        
        // Enable real-time progress updates
        realtimeUpdates: true
    },
    
    // Timeouts and limits
    TIMEOUTS: {
        // Analysis request timeout (milliseconds)
        analysisTimeout: 300000,  // 5 minutes
        
        // WebSocket connection timeout (milliseconds)
        websocketTimeout: 10000,  // 10 seconds
        
        // WebSocket reconnection attempts
        maxReconnectAttempts: 5
    }
};

// Export configuration
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}
