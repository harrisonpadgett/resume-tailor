# Resume Tailor

Resume Tailor is an automated, standalone web application designed to optimize resumes for Applicant Tracking Systems (ATS). It extracts your base experience from a LaTeX document, safely scrapes target job descriptions, and injects ATS-relevant keywords directly into your existing bullet points. It then compiles a perfectly formatted, tailored LaTeX PDF—all while keeping the length strictly to one page.

## Technologies Used

*   **Backend Engine**: FastAPI (Python) for robust, RESTful asynchronous processing.
*   **Frontend Dashboard**: React (Vite) for a responsive, modern single-page application.
*   **AI Engine**: OpenRouter API (Gemini models) for keyword extraction and contextual bullet tailoring.
*   **LaTeX Compilation**: Tectonic, a self-contained modern XeTeX engine for compiling PDFs directly on the server.
*   **Web Scraping**: Trafilatura and BeautifulSoup for high-performance job description extraction.

## Pipeline Architecture

1.  **Resume Extraction**: Users upload their base `.tex` resume. The backend parses and extracts their experience and projects into a structured JSON representation.
2.  **Job Scraping**: Extracts job description text and company metadata from a provided URL.
3.  **Keyword Extraction**: The AI analyzes the job description to identify concrete, ATS-relevant technical skills, methodologies, and tools.
4.  **Contextual Tailoring**: The AI modifies original resume bullets to seamlessly include identified keywords while strictly avoiding hallucinations.
5.  **Page-Fill Estimation**: Before LaTeX compilation, the system estimates vertical space to guarantee the modifications won't spill onto a second page.
6.  **LaTeX Rendering & PDF**: The tailored JSON is injected back into the `resume_template.tex` via placeholders, and Tectonic compiles it into a downloadable PDF.

## Installation

### 1. Backend Dependencies

Install the required Python packages in the root directory:

```bash
pip install fastapi uvicorn pydantic beautifulsoup4 requests google-genai python-dotenv trafilatura loguru openai
```

Install the Tectonic LaTeX compiler on your system:

```bash
# macOS
brew install tectonic

# Linux
cargo install tectonic
```

### 2. Frontend Dependencies

Navigate to the frontend directory and install the Node packages:

```bash
cd frontend
npm install
```

### 3. Configuration

Create a `.env` file in the root directory and add your OpenRouter API key:

```text
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

## Running the Application

Because this is a decoupled application, you must run both the backend API and the frontend dashboard simultaneously in two separate terminal windows.

### Terminal 1: Start the FastAPI Backend
From the root project directory:
```bash
uvicorn api.main:app --port 8000 --reload
```
*Note: API logs and errors will be written to `api.log` in the root directory.*

### Terminal 2: Start the React Frontend
From the `frontend` directory:
```bash
cd frontend
npm run dev
```

Once both servers are running, open **http://localhost:5173/** in your web browser to access the Resume Tailor dashboard.

## Input Data Requirements

To successfully extract and tailor resumes, the system relies on a base template:

1.  **Base Resume**: Upload any valid `.tex` file using the upload box on the dashboard.
2.  **`resume_template.tex`**: Ensure this file exists in the root directory. It must contain the necessary placeholders (`{{EXPERIENCE}}`, `{{PROJECTS}}`, etc.) where the backend will inject the newly tailored content.
3.  **Sample Testing**: You can click the "Use Sample Resume" button on the dashboard to instantly load the default `experience.json` and bypass the extraction step for faster testing.