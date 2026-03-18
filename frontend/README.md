# CloudFormation Security Analyzer — Frontend

React + TypeScript SPA built with [Vite](https://vite.dev/) and [Cloudscape Design System](https://cloudscape.design/).

## Setup

```bash
npm install
```

## Development

```bash
npm run dev
```

Opens at `http://localhost:5173`. The dev server proxies API calls — configure your backend URL in `src/config.ts`.

## Build

```bash
npm run build
```

Output goes to `dist/`. Deploy to S3 + CloudFront:

```bash
aws s3 sync dist/ s3://YOUR_FRONTEND_BUCKET/
```

## Test

```bash
npm test           # run once
npm run test:watch # watch mode
```

## Configuration

Edit `src/config.ts` to set your backend endpoints:

- `EKS_API_URL` — your ALB endpoint (HTTPS)
- `EKS_WS_URL` — your ALB WebSocket endpoint (WSS)
- Localhost URLs are auto-detected for local development
