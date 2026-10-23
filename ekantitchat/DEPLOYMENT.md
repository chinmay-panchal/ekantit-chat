# EkantitChat — Complete Architecture & Deployment Guide

This document explains the full architecture, cloud infrastructure, and step-by-step deployment workflow used to host **EkantitChat** across both frontend and backend on 100% free, production-ready cloud tiers.

---

## 1. High-Level Architecture

```
                          ┌─────────────────────────────────────┐
                          │         CLIENT BROWSER              │
                          │   (Desktop, Mobile, Tablet)         │
                          └──────────────────┬──────────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       │                                           │
                       ▼                                           ▼
          ┌───────────────────────────┐               ┌──────────────────────────┐
          │   FIREBASE HOSTING (CDN)  │               │   HUGGING FACE SPACES    │
          │   • Static SPA Web bundle │               │   • FastAPI (Python 3.11)│
          │   • Global CDN + SSL      │               │   • 16 GB RAM + 2 vCPU   │
          │   • ekantit-chat.web.app  │               │   • 10,308 Vector Pairs  │
          └─────────────┬─────────────┘               └────────────┬─────────────┘
                        │                                          │
                        ▼                                          ▼
          ┌───────────────────────────┐               ┌──────────────────────────┐
          │      CLOUD FIRESTORE      │               │       GEMINI AI          │
          │   • users/{uid}/sessions  │               │   • gemini-embedding-2   │
          │   • Anonymous Firebase    │               │   • gemini-3.1-flash-lite│
          │     Authentication        │               │   • Hinglish grounding   │
          └───────────────────────────┘               └──────────────────────────┘
```

---

## 2. Technology Stack & Why Each Was Chosen

### Frontend: Flutter Web + Firebase
| Technology | Role | Why it was chosen |
| :--- | :--- | :--- |
| **Flutter 3.44 (Web)** | UI Application | Renders identical UI, rich animations, and Hindi typography across desktop and mobile browsers from a single codebase. |
| **Firebase Hosting** | Web CDN & SSL | Free global CDN that serves static web assets instantly with automatic HTTPS (`https://ekantit-chat.web.app`) and SPA routing. |
| **Cloud Firestore** | Cloud Database | Scalable NoSQL document database that persists chat history, titles, and matched episode citations under `users/{uid}/sessions/{sessionId}`. |
| **Firebase Anonymous Auth** | Authentication | Automatically gives every browser visitor a secure cryptographic `uid` without forcing them to create an account or sign in. |
| **SharedPreferences** | Local Cache | Stores chats in browser IndexedDB for instant, zero-latency rendering even before network responses arrive. |

### Backend: FastAPI + Gemini RAG
| Technology | Role | Why it was chosen |
| :--- | :--- | :--- |
| **FastAPI + Uvicorn** | REST API Server | Fast, asynchronous Python web server with built-in Pydantic validation and CORS headers. |
| **Hugging Face Spaces** | Cloud Backend Host | Offers **16 GB RAM and 2 vCPUs completely free** with no credit card required. Essential for keeping the 478 MB vector embeddings cache in memory. |
| **Gemini Embedding 2** | Vector Embeddings | High-dimensional semantic vectors generated for 10,308 Satsang Q&A turns. |
| **Gemini 3.1 Flash Lite** | Generation & Rewriting | Performs multi-turn query rewriting (context resolution) and generates grounded spiritual answers in Maharaj Ji's Hinglish voice. |

---

## 3. Deployment Details

### A. Frontend Deployment (Firebase Hosting)

1. **Configuration files:**
   - [`.firebaserc`](file:///.firebaserc): Links the local project to Firebase project `ekantit-chat`.
   - [`firebase.json`](file:///firebase.json): Configures the public directory (`build/web`) and SPA rewrites (`/index.html`).
   - [`lib/firebase_options.dart`](file:///lib/firebase_options.dart): Automatically generated Firebase credentials for Web.

2. **Build and Deploy Commands:**
   ```bash
   # 1. Compile Flutter Web for production
   flutter build web

   # 2. Deploy to Firebase Hosting
   firebase deploy --only hosting
   ```
   **Live URL:** [https://ekantit-chat.web.app](https://ekantit-chat.web.app)

---

### B. Database & Auth Setup (Firebase Console)

1. **Firestore Rules:**
   Firestore is created in standard edition (`asia-south1`). Documents are stored under:
   ```
   users/{userId}/sessions/{sessionId}
   ```
2. **Anonymous Authentication:**
   Enabled under Firebase Console → **Authentication** → **Sign-in method** → **Anonymous**.

---

### C. Backend Deployment (Render)

1. **Files Prepared in `premanand-poc`:**
   - `Dockerfile`: Configured with Python 3.11-slim, exposing port `${PORT:-7860}`.
   - `requirements.txt`: Minimal dependencies (`fastapi`, `uvicorn`, `google-genai`, `python-dotenv`).
   - `embeddings_cache.jsonl`: 478 MB vector cache (10,308 Q&A pairs).
   - `server.py` & `rag.py`: Conversational RAG pipeline.

2. **To Deploy to Render:**
   - Render is connected to the GitHub repository on branch `main`.
   - Simply push commits to GitHub:
   ```bash
   git add premanand-poc/rag.py premanand-poc/server.py
   git commit -m "chore: update RAG prompt rules"
   git push origin main
   ```
   Render automatically detects changes, rebuilds, and redeploys to:
   ```
   https://ekantit-chat.onrender.com
   ```

3. **Configure API Key in Render:**
   - In Render Dashboard → Your Web Service → **Environment Variables**:
     - Key: `GEMINI_API_KEY`
     - Value: `<YOUR_GEMINI_API_KEY>`

4. **Connect Frontend to Backend:**
   The frontend is configured with the Render endpoint as its default:
   ```
   https://ekantit-chat.onrender.com
   ```

---

## 4. Local Development & Instant Testing (Optional)

If you wish to run the backend on your laptop and test through the live web app without waiting for cloud builds:

1. **Start backend locally:**
   ```bash
   cd /Users/shadowwolf/premanand-poc
   source .venv/bin/activate
   uvicorn server:app --host 0.0.0.0 --port 8000
   ```
2. **Start ngrok tunnel (HTTPS):**
   ```bash
   ngrok http 8000
   ```
3. Paste the generated `https://xxxx.ngrok-free.app` URL into the web app's **Backend URL** settings dialog.

---

## 5. Summary of Costs

| Service | Plan | Monthly Cost |
| :--- | :--- | :--- |
| **Firebase Hosting** | Spark Plan (Free) | **$0.00** (Up to 10 GB storage / 360 MB/day) |
| **Cloud Firestore** | Spark Plan (Free) | **$0.00** (50,000 reads, 20,000 writes / day) |
| **Firebase Authentication** | Spark Plan (Free) | **$0.00** (Unlimited anonymous auth) |
| **Hugging Face Spaces** | Free CPU Tier | **$0.00** (2 vCPU, 16 GB RAM permanently free) |
| **Total Cost** | | **$0.00 / month (100% Free)** |
