FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f AS builder
RUN corepack enable pnpm
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginx:alpine@sha256:892bb2152464f0c5d8972593a5f5afaf8054552580b699d95f8ff4af08c2d33d AS runner
COPY --from=builder /app/out /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Defined (even empty) so the template step substitutes it; extra img-src origins for the CSP.
ENV CARAPACE_CSP_IMG_SRC_EXTRA=""
EXPOSE 80
