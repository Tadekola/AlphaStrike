# Running AlphaStrike in Docker

## Prerequisites
- Docker installed and running.

## Build
If you haven't already built the image:

```bash
docker build -t alphastrike .
```

## Run

### Option 1: Passing Environment Variables Directly (Recommended)
You can pass your Tradier token directly to the container:

```bash
docker run -p 8501:8501 -e TRADIER_TOKEN=your_token_here alphastrike
```

### Option 2: Mounting an .env file
If you have a local `.env` file (make sure it is not committed to git!), you can mount it or pass it as an env file:

```bash
# Using --env-file (easiest)
docker run -p 8501:8501 --env-file .env alphastrike
```

## Access
Open your browser to: [http://localhost:8501](http://localhost:8501)
