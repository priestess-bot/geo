FROM node:22-slim

WORKDIR /app

COPY apps/web/package.json ./package.json
COPY apps/web/package-lock.json ./package-lock.json
RUN npm ci

COPY apps/web ./

CMD ["npm", "run", "dev"]
