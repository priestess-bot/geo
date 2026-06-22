FROM node:22-slim

WORKDIR /app

COPY apps/customer-web/package.json ./package.json
COPY apps/customer-web/package-lock.json ./package-lock.json
RUN npm ci

COPY apps/customer-web ./

CMD ["npm", "run", "dev"]
