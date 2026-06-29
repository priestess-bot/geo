FROM node:22-slim

WORKDIR /app

COPY apps/dashboard-web/package.json ./package.json
COPY apps/dashboard-web/package-lock.json ./package-lock.json
RUN npm ci

COPY apps/dashboard-web ./

CMD ["npm", "run", "dev"]
