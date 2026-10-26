# Keep this version aligned with package.json and package-lock.json. The upstream
# image contains browsers and their system dependencies, without runner apt work.
FROM mcr.microsoft.com/playwright:v1.64.1-noble@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea

WORKDIR /opt/qc-tool-browser
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY playwright.config.cjs uploads.spec.cjs ./
CMD ["npm", "test"]
