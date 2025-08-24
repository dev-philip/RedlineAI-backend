# 🧠 Redline AI – The Agentic Contract Reviewer & SLA Copilot

**AI-powered contract reviewer that ingests agreements, extracts key clauses, flags risks, drafts redlines, and generates plain-language summaries.**

--> Repository Name - RedlineAI-backend
--> Link : https://github.com/dev-philip/RedlineAI-backend
--> Description - Redline AI – The Agentic Contract Reviewer & SLA Copilot backend service

---

## 🎯 Problem

Contracts hide critical risks in fine print. Busy professionals and non-lawyers often miss:

- Rent escalations
- Auto-renewals
- Uptime exceptions
- Restrictive jurisdictions
- Data-use loopholes
- Hidden fees

These oversights lead to **costly mistakes, delays, and risky commitments**.

---

## 💡 Solution

**Redline AI** acts as your **contract copilot**:

- **Ingest & Structure:** Upload PDF/DOCX → OCR → extract clauses + labels
- **Risk & Compare:** Match clauses to policy/precedent with **vector similarity search (TiDB Serverless)**
- **Decide & Act:** Score risk, propose redlines, notify stakeholders, schedule obligations
- **Explain:** Generate **clear rationales & summaries** for business/ops/legal teams

---

## ⚙️ Features

- 📂 Contract ingestion (PDF/DOCX with OCR)
- 🏷️ Clause extraction & tagging (Uptime, Termination, Data Use, etc.)
- 🔍 Vector search against internal policy & past approved language
- 🚨 Risk scoring & redline suggestions
- 📅 Obligation reminders (renewal dates, reporting deadlines)
- 📊 Dashboard + audit log (planned)

---

## 🚀 Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/)
- **Frontend:** React + Tailwind (UI, clause viewer, dashboard)
- **LLM/Embeddings:** OpenAI + LangChain
- **Vector DB:** TiDB Serverless (VECTOR KNN search)
- **Database:** PostgreSQL
- **Infra:** Docker, Uvicorn/Gunicorn, Redis

---

## 🛠️ Quickstart

Clone the repo and install dependencies:

git clone https://github.com/dev-philip/RedlineAI-backend
cd RedlineAI-backend
pip install -r requirements.txt

## How to run the project

1. Create a New Conda Environment
   `conda create -n redline-ai-env python=3.11`
2. Create a New Conda Environment
   `conda activate redline-ai-env`

3. Install pip inside the conda environment (optional, but safe to check)
   `conda install pip`

4. Install your dependencies from requirements.txt
   `pip install -r requirements.txt`

5. Verify Installed Packages
   `pip list`

6. If you want to save the exact environment for others to use with Conda, you can later export:
   `conda env export > environment.yml`
   OR recreate it using:
7. `conda env create -f environment.yml`

8. Use pip install and add package to requirement.txt file
   `pip install pydantic-settings`
   `echo pydantic-settings >> requirements.txt`
   OR Option 2: Re-freeze your environment. After installing the package, run:
   `pip freeze > requirements.txt`
   Note : This overwrites requirements.txt with everything currently installed in your environment — good for syncing it all, but might include extras you don’t want.

9. Start Project Server :
   `uvicorn app.main:app --reload`

## Some endpoint to check

http://127.0.0.1:8000 → Welcome message
http://127.0.0.1:8000/docs → Swagger UI

```

```
