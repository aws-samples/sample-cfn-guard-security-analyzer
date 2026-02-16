# CloudFormation Security Analyzer - Static Frontend

This directory contains the static frontend application for the CloudFormation Security Analyzer, migrated from the Flask-based monolithic application to work with AWS serverless services (API Gateway + Lambda + Step Functions).

## Architecture

The frontend is a pure static web application that:
- Runs entirely in the browser (no server-side rendering)
- Communicates with backend via API Gateway REST and WebSocket APIs
- Can be hosted on S3 + CloudFront for global distribution
- Supports real-time progress updates via WebSocket connections

## Files

### Core Files

- **index.html** - Main HTML page with UI structure
- **styles.css** - CSS styles extracted from Flask template
- **app.js** - Main application logic with API Gateway integration
- **config.js** - Configuration file for API endpoints and settings

### Configuration

Before deploying, update `config.js` with your deployed API Gateway endpoints:

```javascript
const CONFIG = {
    // REST API endpoint
    API_BASE_URL: 'https://YOUR_API_GATEWAY_ID.execute-api.YOUR_REGION.amazonaws.com/prod',
    
    // WebSocket API endpoint
    WEBSOCKET_URL: 'wss://YOUR_WEBSOCKET_API_ID.execute-api.YOUR_REGION.amazonaws.com/prod',
    
    // Authentication settings
    AUTH: {
        useIAM: false,
        useCognito: false
    }
};
```

## API Integration

### REST API Endpoints

The frontend expects the following REST API endpoints:

1. **POST /analysis/quick** - Start quick security analysis
   - Request: `{ url: string, type: 'quick' }`
   - Response: `{ analysisId: string, status: string }`

2. **POST /analysis/detailed** - Start detailed security analysis
   - Request: `{ url: string, type: 'detailed' }`
   - Response: `{ analysisId: string, status: string }`

3. **GET /analysis/{analysisId}** - Get analysis results
   - Response: `{ analysisId: string, results: object }`

4. **POST /reports/{analysisId}** - Generate PDF report
   - Response: `{ reportUrl: string }`

### WebSocket API

The frontend connects to the WebSocket API for real-time updates:

1. **Connection** - Establish WebSocket connection
2. **Subscribe** - Subscribe to analysis updates
   - Send: `{ action: 'subscribe', analysisId: string }`
3. **Progress Updates** - Receive progress messages
   - Receive: `{ type: 'progress', progress: number, message: string }`
4. **Property Complete** - Receive property analysis results
   - Receive: `{ type: 'property_complete', property: object }`
5. **Analysis Complete** - Receive completion notification
   - Receive: `{ type: 'analysis_complete', analysisId: string }`

## Deployment

### Option 1: S3 + CloudFront (Recommended)

1. Upload all files to an S3 bucket configured for static website hosting
2. Create a CloudFront distribution pointing to the S3 bucket
3. Update `config.js` with your API Gateway endpoints
4. Access the application via the CloudFront URL

### Option 2: Local Development

1. Update `config.js` with local development endpoints
2. Serve files using a local web server:
   ```bash
   # Using Python
   python3 -m http.server 8000
   
   # Using Node.js
   npx http-server -p 8000
   ```
3. Access the application at `http://localhost:8000`

## Migration from Flask

### Changes Made

1. **Removed Server-Side Rendering**
   - Extracted HTML from Flask template
   - Removed Jinja2 template syntax
   - Converted to pure static HTML

2. **Replaced Flask Endpoints**
   - `/analyze` → API Gateway REST endpoint
   - WebSocket events → API Gateway WebSocket API
   - `/api/results/{sessionId}` → API Gateway REST endpoint

3. **Updated WebSocket Integration**
   - Replaced Socket.IO with native WebSocket API
   - Updated message format to match API Gateway WebSocket
   - Added reconnection logic

4. **Added Authentication Support**
   - Placeholder for AWS IAM authentication
   - Placeholder for AWS Cognito authentication
   - Configurable via `config.js`

### Compatibility

The frontend maintains the same user experience as the Flask version:
- Same UI/UX design
- Same real-time progress tracking
- Same property-by-property streaming
- Same analysis features

## Authentication

### AWS IAM Authentication

To enable IAM authentication:

1. Set `CONFIG.AUTH.useIAM = true` in `config.js`
2. Implement AWS Signature Version 4 signing for API requests
3. Use AWS SDK for JavaScript to handle signing

### AWS Cognito Authentication

To enable Cognito authentication:

1. Set `CONFIG.AUTH.useCognito = true` in `config.js`
2. Configure Cognito User Pool details in `config.js`
3. Implement Cognito authentication flow using AWS Amplify
4. Store and use JWT tokens for API requests

## Testing

### Manual Testing

1. Open the application in a browser
2. Enter a CloudFormation documentation URL
3. Click "Start Security Analysis"
4. Verify:
   - WebSocket connection establishes
   - Progress updates appear in real-time
   - Property cards appear as analysis completes
   - Final results display correctly

### Browser Compatibility

Tested and supported browsers:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Troubleshooting

### WebSocket Connection Fails

- Check that `WEBSOCKET_URL` in `config.js` is correct
- Verify WebSocket API is deployed and accessible
- Check browser console for connection errors
- Ensure CORS is configured correctly on API Gateway

### API Requests Fail

- Check that `API_BASE_URL` in `config.js` is correct
- Verify REST API is deployed and accessible
- Check browser console for HTTP errors
- Ensure CORS is configured correctly on API Gateway

### Authentication Errors

- Verify authentication configuration in `config.js`
- Check that IAM/Cognito credentials are valid
- Ensure API Gateway has correct authorization settings

## Future Enhancements

- [ ] Implement AWS IAM authentication
- [ ] Implement AWS Cognito authentication
- [ ] Add offline support with Service Workers
- [ ] Add batch analysis UI
- [ ] Add PDF report download functionality
- [ ] Add analysis history and caching
- [ ] Add dark mode support
- [ ] Add accessibility improvements (ARIA labels, keyboard navigation)

## License

Same as parent project.
