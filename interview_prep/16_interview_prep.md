# Phase 16 — Complete Interview Preparation

This document provides 100 interview questions ranging from Junior to Principal level based entirely on the PDFTalk codebase.

## Junior Engineer

**[Security]** Q1: Explain how JWT authentication is implemented in PDFTalk and why it is stateless.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q2: Why does the application use HttpOnly cookies for refresh tokens but JSON bodies for access tokens?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q3: How would you implement instant token revocation for a stateless JWT architecture?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q4: Explain the protection mechanisms against CSRF and XSS attacks implemented in the auth routers.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q5: Detail the token rotation strategy and how it prevents replay attacks if a token is stolen.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Scalability]** Q26: Describe the presigned URL flow for document uploads. Why bypass FastAPI?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q27: What happens to the application if the Redis queue broker crashes?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q28: How do you scale the asynchronous Celery/RQ workers independently of the web API?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q29: Explain how Nginx terminates TLS and routes traffic in the Docker compose setup.

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q30: If 100,000 users upload PDFs at exactly the same time, which component fails first and how do you fix it?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Data / AI]** Q51: What is pgvector and why did the team choose it over Pinecone?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q52: How does the HNSW index work and why is it faster than exact KNN search?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q53: Explain how the SQLAlchemy chunk model links vectors to users to speed up similarity queries.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q54: Why is chunking overlapping text critical for LLM context generation?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q55: Walk through the RAG pipeline from user query to streaming Server-Sent Events response.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[DevOps]** Q76: Explain the CI/CD pipeline defined in GitHub Actions.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q77: How does the integration test suite use Docker and Pytest fixtures?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q78: What is the purpose of Alembic migrations and how do they tie into the deployment flow?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q79: Explain how Prometheus and Grafana monitor the FastAPI endpoints.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q80: How would you implement blue-green deployments for this specific stack on AWS?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

## Mid Engineer

**[Security]** Q6: Explain how JWT authentication is implemented in PDFTalk and why it is stateless.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q7: Why does the application use HttpOnly cookies for refresh tokens but JSON bodies for access tokens?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q8: How would you implement instant token revocation for a stateless JWT architecture?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q9: Explain the protection mechanisms against CSRF and XSS attacks implemented in the auth routers.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q10: Detail the token rotation strategy and how it prevents replay attacks if a token is stolen.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Scalability]** Q31: Describe the presigned URL flow for document uploads. Why bypass FastAPI?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q32: What happens to the application if the Redis queue broker crashes?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q33: How do you scale the asynchronous Celery/RQ workers independently of the web API?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q34: Explain how Nginx terminates TLS and routes traffic in the Docker compose setup.

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q35: If 100,000 users upload PDFs at exactly the same time, which component fails first and how do you fix it?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Data / AI]** Q56: What is pgvector and why did the team choose it over Pinecone?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q57: How does the HNSW index work and why is it faster than exact KNN search?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q58: Explain how the SQLAlchemy chunk model links vectors to users to speed up similarity queries.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q59: Why is chunking overlapping text critical for LLM context generation?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q60: Walk through the RAG pipeline from user query to streaming Server-Sent Events response.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[DevOps]** Q81: Explain the CI/CD pipeline defined in GitHub Actions.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q82: How does the integration test suite use Docker and Pytest fixtures?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q83: What is the purpose of Alembic migrations and how do they tie into the deployment flow?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q84: Explain how Prometheus and Grafana monitor the FastAPI endpoints.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q85: How would you implement blue-green deployments for this specific stack on AWS?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

## Senior Engineer

**[Security]** Q11: Explain how JWT authentication is implemented in PDFTalk and why it is stateless.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q12: Why does the application use HttpOnly cookies for refresh tokens but JSON bodies for access tokens?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q13: How would you implement instant token revocation for a stateless JWT architecture?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q14: Explain the protection mechanisms against CSRF and XSS attacks implemented in the auth routers.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q15: Detail the token rotation strategy and how it prevents replay attacks if a token is stolen.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Scalability]** Q36: Describe the presigned URL flow for document uploads. Why bypass FastAPI?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q37: What happens to the application if the Redis queue broker crashes?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q38: How do you scale the asynchronous Celery/RQ workers independently of the web API?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q39: Explain how Nginx terminates TLS and routes traffic in the Docker compose setup.

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q40: If 100,000 users upload PDFs at exactly the same time, which component fails first and how do you fix it?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Data / AI]** Q61: What is pgvector and why did the team choose it over Pinecone?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q62: How does the HNSW index work and why is it faster than exact KNN search?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q63: Explain how the SQLAlchemy chunk model links vectors to users to speed up similarity queries.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q64: Why is chunking overlapping text critical for LLM context generation?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q65: Walk through the RAG pipeline from user query to streaming Server-Sent Events response.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[DevOps]** Q86: Explain the CI/CD pipeline defined in GitHub Actions.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q87: How does the integration test suite use Docker and Pytest fixtures?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q88: What is the purpose of Alembic migrations and how do they tie into the deployment flow?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q89: Explain how Prometheus and Grafana monitor the FastAPI endpoints.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q90: How would you implement blue-green deployments for this specific stack on AWS?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

## Staff Engineer

**[Security]** Q16: Explain how JWT authentication is implemented in PDFTalk and why it is stateless.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q17: Why does the application use HttpOnly cookies for refresh tokens but JSON bodies for access tokens?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q18: How would you implement instant token revocation for a stateless JWT architecture?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q19: Explain the protection mechanisms against CSRF and XSS attacks implemented in the auth routers.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q20: Detail the token rotation strategy and how it prevents replay attacks if a token is stolen.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Scalability]** Q41: Describe the presigned URL flow for document uploads. Why bypass FastAPI?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q42: What happens to the application if the Redis queue broker crashes?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q43: How do you scale the asynchronous Celery/RQ workers independently of the web API?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q44: Explain how Nginx terminates TLS and routes traffic in the Docker compose setup.

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q45: If 100,000 users upload PDFs at exactly the same time, which component fails first and how do you fix it?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Data / AI]** Q66: What is pgvector and why did the team choose it over Pinecone?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q67: How does the HNSW index work and why is it faster than exact KNN search?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q68: Explain how the SQLAlchemy chunk model links vectors to users to speed up similarity queries.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q69: Why is chunking overlapping text critical for LLM context generation?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q70: Walk through the RAG pipeline from user query to streaming Server-Sent Events response.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[DevOps]** Q91: Explain the CI/CD pipeline defined in GitHub Actions.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q92: How does the integration test suite use Docker and Pytest fixtures?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q93: What is the purpose of Alembic migrations and how do they tie into the deployment flow?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q94: Explain how Prometheus and Grafana monitor the FastAPI endpoints.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q95: How would you implement blue-green deployments for this specific stack on AWS?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

## Principal Engineer

**[Security]** Q21: Explain how JWT authentication is implemented in PDFTalk and why it is stateless.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q22: Why does the application use HttpOnly cookies for refresh tokens but JSON bodies for access tokens?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q23: How would you implement instant token revocation for a stateless JWT architecture?

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q24: Explain the protection mechanisms against CSRF and XSS attacks implemented in the auth routers.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Security]** Q25: Detail the token rotation strategy and how it prevents replay attacks if a token is stolen.

*Answer Guidance:* Expected: Detail HttpOnly cookies, 15m JWT TTL, Redis denylists, XSS/CSRF mitigations.

**[Scalability]** Q46: Describe the presigned URL flow for document uploads. Why bypass FastAPI?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q47: What happens to the application if the Redis queue broker crashes?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q48: How do you scale the asynchronous Celery/RQ workers independently of the web API?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q49: Explain how Nginx terminates TLS and routes traffic in the Docker compose setup.

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Scalability]** Q50: If 100,000 users upload PDFs at exactly the same time, which component fails first and how do you fix it?

*Answer Guidance:* Expected: Detail S3 offloading, Redis bottleneck, Horizontal scaling of workers, RDS migration.

**[Data / AI]** Q71: What is pgvector and why did the team choose it over Pinecone?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q72: How does the HNSW index work and why is it faster than exact KNN search?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q73: Explain how the SQLAlchemy chunk model links vectors to users to speed up similarity queries.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q74: Why is chunking overlapping text critical for LLM context generation?

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[Data / AI]** Q75: Walk through the RAG pipeline from user query to streaming Server-Sent Events response.

*Answer Guidance:* Expected: Detail HNSW graphs, cosine similarity, overlapping chunks, ACID compliance of pgvector.

**[DevOps]** Q96: Explain the CI/CD pipeline defined in GitHub Actions.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q97: How does the integration test suite use Docker and Pytest fixtures?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q98: What is the purpose of Alembic migrations and how do they tie into the deployment flow?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q99: Explain how Prometheus and Grafana monitor the FastAPI endpoints.

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.

**[DevOps]** Q100: How would you implement blue-green deployments for this specific stack on AWS?

*Answer Guidance:* Expected: Detail Pytest fixtures with DB rollbacks, Alembic upgrades, Prometheus /metrics scraping.
