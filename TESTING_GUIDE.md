# Testing Guide - CloudFormation Security Analyzer

## System Status: READY FOR TESTING ✅

All components are deployed and ready for testing.

## Quick Start Testing

### 1. API Testing (Backend Only)

#### Test Quick Scan
```bash
curl -X POST https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev/analysis/quick \
  -H "Content-Type: application/json" \
  -d '{
    "resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html",
    "analysisType": "quick"
  }'
```

**Expected Response:**
```json
{
  "analysisId": "uuid-here",
  "status": "COMPLETED",
  "results": {
    "resourceType": "AWS::S3::Bucket",
    "properties": [
      {
        "name": "BucketEncryption",
        "riskLevel": "CRITICAL",
        "securityImplication": "...",
        "recommendation": "..."
      }
    ],
    "analysisTimestamp": "2026-02-02T..."
  },
  "message": "Quick scan completed successfully"
}
```

#### Test Detailed Analysis
```bash
curl -X POST https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev/analysis/detailed \
  -H "Content-Type: application/json" \
  -d '{
    "resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html",
    "analysisType": "detailed"
  }'
```

**Expected Response:**
```json
{
  "analysisId": "uuid-here",
  "status": "IN_PROGRESS",
  "message": "Detailed analysis started successfully"
}
```

#### Check Analysis Status
```bash
# Replace {analysisId} with the ID from previous response
curl https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev/analysis/{analysisId}
```

### 2. Frontend Testing (UI)

#### Access Frontend
**S3 Website URL:** http://cfn-security-frontend-dev-111111111111.s3-website-us-east-1.amazonaws.com

**CloudFront URL:** (Check CloudFormation outputs for CloudFront distribution URL)

#### Test Workflow
1. Open frontend URL in browser
2. Enter CloudFormation resource URL:
   ```
   https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html
   ```
3. Click "Quick Scan" button
4. Verify results display within 30 seconds
5. Try "Detailed Analysis" button
6. Verify real-time progress updates (if WebSocket configured)

### 3. Monitor Execution

#### CloudWatch Logs
```bash
# Lambda orchestrator logs
aws logs tail /aws/lambda/cfn-security-orchestrator-dev --follow

# Step Functions workflow logs
aws logs tail /aws/vendedlogs/states/cfn-security-workflow-dev --follow

# AgentCore agent logs
aws logs tail /aws/bedrock-agentcore/runtimes/cfn_security_analyzer-mRHhTSCZIG-DEFAULT --follow
```

#### Step Functions Console
```bash
# List recent executions
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:111111111111:stateMachine:cfn-security-workflow-dev \
  --max-results 10

# Describe specific execution
aws stepfunctions describe-execution \
  --execution-arn <execution-arn>
```

#### DynamoDB Data
```bash
# Check analysis records
aws dynamodb scan \
  --table-name cfn-security-analysis-state-dev \
  --limit 10
```

## Detailed Test Scenarios

### Scenario 1: Quick Scan - S3 Bucket
**Resource:** AWS::S3::Bucket
**URL:** https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html
**Expected Duration:** < 30 seconds
**Expected Properties:** BucketEncryption, PublicAccessBlockConfiguration, VersioningConfiguration, LoggingConfiguration

### Scenario 2: Quick Scan - Lambda Function
**Resource:** AWS::Lambda::Function
**URL:** https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-lambda-function.html
**Expected Duration:** < 30 seconds
**Expected Properties:** Environment variables encryption, VPC configuration, IAM role, Tracing

### Scenario 3: Detailed Analysis - RDS Instance
**Resource:** AWS::RDS::DBInstance
**URL:** https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-rds-dbinstance.html
**Expected Duration:** 2-5 minutes
**Expected Properties:** StorageEncrypted, PubliclyAccessible, BackupRetentionPeriod, EnableCloudwatchLogsExports

### Scenario 4: Error Handling - Invalid URL
**Request:**
```bash
curl -X POST https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev/analysis/quick \
  -H "Content-Type: application/json" \
  -d '{
    "resourceUrl": "not-a-valid-url",
    "analysisType": "quick"
  }'
```
**Expected Response:** 400 Bad Request with error message

### Scenario 5: Error Handling - Non-existent Resource
**Request:**
```bash
curl -X POST https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev/analysis/quick \
  -H "Content-Type: application/json" \
  -d '{
    "resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-nonexistent.html",
    "analysisType": "quick"
  }'
```
**Expected Behavior:** Agent should handle gracefully and return appropriate error

## What's Working

✅ **Backend Infrastructure**
- API Gateway REST endpoints
- Lambda orchestrator with AgentCore integration
- Step Functions workflow with agent invocation
- DynamoDB state management
- S3 reports bucket

✅ **AgentCore Agents**
- Security Analyzer Agent (quick scans)
- Crawler Agent (property extraction)
- Property Analyzer Agent (detailed analysis)

✅ **Frontend**
- Static files deployed to S3
- API endpoint configured
- UI ready for testing

## What's NOT Yet Implemented

⚠️ **WebSocket Real-Time Updates**
- WebSocket API exists but not fully configured
- Frontend has WebSocket client code but needs WebSocket API URL
- Step Functions workflow doesn't send progress updates yet

⚠️ **Monitoring Dashboard**
- CloudWatch logs are working
- No custom dashboard created yet (Task 11)
- No CloudWatch alarms configured yet (Task 11)

⚠️ **PDF Report Generation**
- Report Generator Lambda exists
- Not tested yet
- Endpoint: `POST /reports/{analysisId}`

⚠️ **Authentication**
- Currently no authentication (open API)
- IAM authentication not configured (Task 15)

⚠️ **Batch Analysis**
- Not implemented yet (Task 13)

## Known Issues

1. **WebSocket URL Not Configured**
   - Frontend config has placeholder WebSocket URL
   - Need to get WebSocket API ID from CloudFormation outputs
   - Update `frontend/config.js` with actual WebSocket URL

2. **Agent Response Parsing**
   - Agents may return text instead of JSON
   - Lambda has fallback handling but may need refinement

3. **Error Messages**
   - Some error messages may not be user-friendly
   - Need to test various failure scenarios

## Troubleshooting

### Issue: API returns 500 error
**Check:**
1. Lambda logs: `aws logs tail /aws/lambda/cfn-security-orchestrator-dev --follow`
2. Lambda permissions: Verify Bedrock AgentCore permissions
3. Agent status: Check if agents are deployed and accessible

### Issue: Analysis never completes
**Check:**
1. Step Functions execution: AWS Console > Step Functions > Executions
2. Step Functions logs: `aws logs tail /aws/vendedlogs/states/cfn-security-workflow-dev --follow`
3. Agent invoker Lambda logs

### Issue: Frontend doesn't load
**Check:**
1. S3 bucket website hosting enabled
2. Bucket policy allows public read
3. CORS configuration on API Gateway

### Issue: Frontend can't connect to API
**Check:**
1. API endpoint in `config.js` is correct
2. CORS headers in API Gateway responses
3. Browser console for errors

## Next Steps After Testing

1. **Fix any issues found during testing**
2. **Configure WebSocket API** for real-time updates
3. **Add monitoring dashboard** (Task 11)
4. **Configure authentication** (Task 15)
5. **Test PDF report generation**
6. **Implement batch analysis** (Task 13)
7. **Performance testing** with multiple concurrent requests
8. **Security testing** (input validation, injection attempts)

## Success Criteria

✅ Quick scan completes in < 30 seconds
✅ Detailed analysis completes in < 5 minutes
✅ Results are accurate and well-formatted
✅ Error handling works correctly
✅ Frontend displays results properly
✅ CloudWatch logs show all operations
✅ DynamoDB stores analysis state correctly

## Contact & Support

For issues or questions:
1. Check CloudWatch logs first
2. Review Step Functions execution history
3. Verify agent deployment status in GenAI Observability Dashboard
4. Check DynamoDB for analysis state

## Testing Checklist

- [ ] Quick scan with S3 Bucket resource
- [ ] Quick scan with Lambda Function resource
- [ ] Quick scan with RDS Instance resource
- [ ] Detailed analysis with S3 Bucket resource
- [ ] Invalid URL error handling
- [ ] Non-existent resource error handling
- [ ] Frontend loads successfully
- [ ] Frontend quick scan button works
- [ ] Frontend displays results correctly
- [ ] CloudWatch logs show agent invocations
- [ ] DynamoDB stores analysis records
- [ ] Step Functions workflow completes successfully
- [ ] PDF report generation (if implemented)
- [ ] Multiple concurrent requests
- [ ] Large resource with many properties

---

**Last Updated:** February 2, 2026
**Environment:** dev
**Region:** us-east-1
**Account:** 111111111111
