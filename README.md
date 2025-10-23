# GIBSI WEB BACKEND
The GIBSI WEB Backend powers the AI-driven trading core of the GIBSI ecosystem.
It provides RESTful APIs for real-time data handling, model inference, trade signal generation, and backtesting, all optimized for practical AI-based stock trading workflows.

Status: Private repository — currently under live testing via
https://crack-akita-brief.ngrok-free.app/

Overview
This backend acts as the central logic layer for GIBSI Striker, connecting the front-end trading interface with AI model pipelines.
Built with Flask and MongoDB, it ensures secure, modular, and scalable processing of market data for both live and simulated environments.

Key Capabilities
LSTM/ML-driven signal generation from OHLCV and technical indicator data

REST endpoints for price prediction, backtesting, and strategy configuration

MongoDB logging of trades and performance metrics

Real-time integration via ngrok tunnel for secure external access

Flexible parameter control for AI models and trading thresholds

Tech Stack
Layer	Technology
Framework	Flask (Python 3.11+)
Data & ML Stack	Pandas, NumPy, TensorFlow, scikit-learn, ta
Database	MongoDB (PyMongo)
API	RESTful JSON endpoints with Flask-RESTPlus
Documentation	Swagger / Flasgger
Security	JWT Authentication, Flask-CORS
Containerization	Docker, Docker Compose
Live Testing	ngrok public tunnel
Docker Image and Kubernetes Deployment
To facilitate easy deployment and scalability, a pre-built arm64 Docker image of the GIBSI WEB Backend is published on Docker Hub to support Kubernetes (K3s) and other container orchestration platforms.

Docker Hub Repository:
gbmultani27/gibsi_web_backend
https://hub.docker.com/repository/docker/gbmultani27/gibsi_web_backend/

Deployment Highlights
Multi-architecture support: Image available for ARM64 devices, suitable for Raspberry Pi clusters running K3s.

Kubernetes ready: Simplifies deployment in lightweight Kubernetes environments.

Continuous updates: Latest tags pushed automatically for ongoing development builds.
