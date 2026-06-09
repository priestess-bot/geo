FROM node:22-slim

WORKDIR /app

COPY apps/web/package.json ./package.json
RUN npm install

COPY apps/web ./

CMD ["npm", "run", "dev"]
