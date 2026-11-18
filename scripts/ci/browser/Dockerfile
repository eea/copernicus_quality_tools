# Keep this version aligned with package.json and package-lock.json. The upstream
# image contains browsers and their system dependencies, without runner apt work.
FROM mcr.microsoft.com/playwright:v1.65.1-noble@sha256:1507cbfc550a63a6b7396791ca4f00df17beb56342d2447b3f106c306f525579

WORKDIR /opt/qc-tool-browser
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY playwright.config.cjs uploads.spec.cjs ./
CMD ["npm", "test"]
