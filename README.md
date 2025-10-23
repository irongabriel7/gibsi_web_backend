# GIBSI WEB BACKEND
The GIBSI WEB Backend powers the AI-driven trading core of the GIBSI ecosystem.
It provides RESTful APIs for real-time data handling, model inference, trade signal generation, and backtesting, all optimized for practical AI-based stock trading workflows.

Status: Private repository — under live testing via
https://crack-akita-brief.ngrok-free.app/

Overview
This backend acts as the central logic layer for GIBSI Striker, connecting the front-end trading interface and AI model pipelines.
Built with Flask and MongoDB, it ensures secure, modular, and scalable processing of market data for both live and simulated environments.

Key Capabilities:

LSTM/ML-driven signal generation from OHLCV and indicator data

REST endpoints for price prediction, backtesting, and strategy configuration

MongoDB logging of trades and performance metrics

Real-time integration through ngrok tunnel for secure external access

Flexible parameter control for AI and trading thresholds

Tech Stack
Layer	Technology
Framework	Flask (Python 3.11+)
Data & ML Stack	Pandas, NumPy, TensorFlow, scikit-learn, ta
Database	MongoDB (PyMongo)
API	RESTful JSON endpoints with Flask-RESTPlus
Documentation	Swagger / Flasgger
Security	JWT Authentication, Flask-CORS
Containerization	Docker, Docker Compose
Live Testing	Ngrok public tunnel
