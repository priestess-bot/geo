FROM node:22-slim

WORKDIR /app

COPY apps/admin-web/package.json ./package.json
COPY apps/admin-web/package-lock.json ./package-lock.json
RUN npm ci

COPY apps/admin-web ./

CMD ["npm", "run", "dev"]
