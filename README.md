# 🧠 GIBSI WEB BACKEND

AI-Driven Trading Intelligence Layer for the GIBSI Ecosystem

Status: 🧩 Private Repository | 🧪 Live Testing via ngrok public tunnel

📘 Overview

The GIBSI WEB Backend powers the AI trading core of the GIBSI ecosystem.
It provides RESTful APIs for real-time data handling, model inference, trade signal generation, and backtesting — all optimized for AI-based stock trading workflows.

This backend acts as the central logic layer for GIBSI Striker, connecting the front-end trading interface with deep learning model pipelines.
Built with Flask and MongoDB, it ensures secure, modular, and scalable processing of market data for both live and simulated environments.

⚙️ Key Capabilities
Feature	Description
🤖 AI Signal Generation	LSTM/ML-driven trade signals derived from OHLCV & technical indicator data
🔗 REST Endpoints	For price prediction, backtesting, and strategy parameter configuration
📊 Data Logging	MongoDB-based trade and performance tracking
🌐 Real-Time Integration	Secure ngrok tunnel for remote front-end access
⚙️ Configurable Parameters	Dynamic control over AI thresholds, trading rules, and indicators
🧱 Scalable Design	Modular Flask-based microservices supporting multiple environments
🧰 Tech Stack
Layer	Technology
Framework	Flask (Python 3.11+)
Data & ML Stack	Pandas, NumPy, TensorFlow, scikit-learn, ta (technical analysis)
Database	MongoDB (PyMongo)
API Layer	RESTful JSON endpoints via Flask-RESTPlus
Documentation	Swagger / Flasgger
Security	JWT Authentication, Flask-CORS
Containerization	Docker, Docker Compose
Live Testing	ngrok public tunnel
🐳 Docker & Kubernetes Deployment

The GIBSI WEB Backend ships as a multi-architecture Docker image for easy deployment on both cloud and edge infrastructures (including Raspberry Pi clusters running K3s).

Deployment Target	Description
Docker Hub	gbmultani27/gibsi_web_backend

Architecture	ARM64 compatible (Raspberry Pi, Jetson Nano, etc.)
Kubernetes Ready	Optimized for lightweight Kubernetes clusters (K3s)
Continuous Updates	Automatically pushed latest build tags for live development
Environment Config	.env-based configuration for ports, DB, and secrets
🚀 Deployment Highlights

🧩 Multi-architecture builds — optimized for ARM64 and x86_64

☁️ Kubernetes-native design — deployable via Helm, kubectl, or K3s manifests

🔁 Auto CI/CD updates — development builds are continuously published to Docker Hub

🔒 Secure by design — includes JWT authentication, HTTPS-ready configuration, and CORS management

📦 Quick Start
# Clone the repository
git clone https://github.com/<your-org>/gibsi_web_backend.git
cd gibsi_web_backend

# Build and run using Docker
docker-compose up --build

# Or run locally (development mode)
python app.py

📡 Live Testing Endpoint
Environment	URL
Testing (ngrok)	https://crack-akita-brief.ngrok-free.app/

🧠 About GIBSI

GIBSI (Generalized Intelligent Broker System Interface) is an evolving AI trading ecosystem that integrates machine learning, real-time analytics, and adaptive strategies to redefine autonomous trading.
