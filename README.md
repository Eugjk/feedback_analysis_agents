# Feedback Analysis Agents (Overview)

This project turns multi-channel online app feedback into a smaller set of ticket-ready product and engineering issues. It is a prototype for product operations teams that need to move from raw customer comments/problems to an actionable actionable tickets with supporting evidence.

The pipeline reads feedback from an Excel workbook, standardizes it into a single dataframe, clusters related comments, asks Gemini to summarize each cluster, validates outlier feedback against the candidate tickets, and merges duplicate ticket themes. The final output is `outputs/final_tickets.csv`.

## The motivation for this project

Customer feedback often arrives through several channels: support tickets, long-form emails, and surveys. The same product issue can appear in many different forms, while unrelated issues can share similar words. Moreover, for large-scale apps, there will be a large number of tickets/emails etc. being processed, which makes manual review tedious. This project explores an agentic workflow that aims to solve this set of problems.

The main design structure is to keep both API usage and ticket volume low. A naive one-agent approach could send every feedback item, or every pair of feedback items, through an LLM for classification and deduplication. That becomes expensive quickly and still tends to produce overlapping tickets. This project instead uses cheap local TF-IDF clustering first, then spends LLM calls only on smaller cluster summaries, ambiguous records, and final ticket merging. The target outcome is fewer model calls per feedback item and fewer duplicate tickets for reviewers to triage.

The intended user is a product, support operations, or engineering triage team that wants a first-pass grouping of customer pain points translated into tickets before human review.

## Data Story

The dataset is synthetic. It is located in `synthetic_online_app_feedback_datasets.xlsx` and was created to mimic realistic feedback for an online app across three channels:

- `Support Tickets`: 20 short support-style complaints
- `Emails`: 15 longer customer email messages
- `Surveys`: 15 survey comments, that may or may not contain customer problems that need to be solved

The synthetic records cover app issues such as OTP/login failure, payment status mismatch, duplicate charging, document upload failures etc. that mimic the real problems users face when using an online app.

The main reason for using synthetic data is due to the nature of the project being a prototype. For a prototype, typically we want to test whether or not the agentic workflow works, not to perfectly model production data. We also need to keep in mind that there are many ways to customize the agents for experimentation purposes.

Moreover, if we can control the dataset to a high degree, we can deliberately introduce outlier tickets (e.g. vague/mixed-topic/irrelevant tickets) to test whether the agentic workflow is robust enough to handle these, so that we can be more well-informed when doing the actual implementation during the POV stages of the project.

Licensing: no external public dataset, web scrape, or third-party licensed corpus is used. Because this is a self-created synthetic dataset, there are no source-specific license obligations from data.gov.sg, Kaggle, Hugging Face, or the open web. 

The dataset also uses artificial customer IDs such as `CUST001` and does not intentionally contain real personal data. The privacy risk would change significantly if real customer feedback were substituted. In that case, redact direct identifiers, minimize sensitive content, confirm authorization to process the data, and avoid sending personal or confidential data to external model APIs without the required legal and vendor controls. 

## How It Works

The workflow is designed as a sequence of narrow decisions instead of one large prompt:

1. `main.py` calls `load_feedback_data()` to create the normalized feedback dataframe from the relative workbook path.
2. `cluster_feedback()` uses TF-IDF with English stopwords and 1-2 grams, followed by KMeans. This gives a cheap first-pass grouping based on shared language before any LLM calls are made, reducing the number of prompts needed per feedback record.
3. `summarise_cluster_with_gemini()` acts as the summarizer agent. It converts each noisy cluster into a ticket-style issue by identifying the most common problem mentioned, recommends an owner, preserves supporting feedback IDs, and flags records that are unrelated to said problem and hence do not belong to the cluster. One call can cover many feedback records.
4. `validate_with_gemini()` acts as the validation agent. It reviews those flagged records against the existing ticket candidates so edge cases are reassigned, split into new tickets, or ignored if they are not actionable.
5. `merge_tickets()` acts as the merging agent. It compares ticket candidates after validation and merges only genuinely duplicate issue descriptions, which reduces backlog noise without hiding source feedback.
6. The pipeline writes intermediate and final CSV/JSON artifacts.


## Output Results

Current generated artifacts include:

- `outputs/processed_feedback.csv`: 50 standardized feedback records
- `outputs/clustered_feedback.csv`: feedback records with `cluster_id`
- `outputs/final_tickets.csv`: final ticket candidates after merge. This is the final artifact.


## How To Run

### Local Python

Use Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local `.env` file:

```bash
GEMINI_API_KEY=your_api_key_here
```

Then run:

```bash
python3 main.py
```

### Docker

Build the image from the repository root:

```bash
docker build -t feedback-analysis-agents .
```

Run the pipeline with your Gemini key from `.env`:

```bash
docker run --rm --env-file .env feedback-analysis-agents
```

To keep generated CSV/JSON outputs on your host machine, mount the project directory:

```bash
docker run --rm --env-file .env -v "$PWD:/app/feedback_analysis_agents" feedback-analysis-agents
```

### Docker Desktop

You can also run the same image from Docker Desktop:

1. Build the image once from the terminal:

```bash
docker build -t feedback-analysis-agents .
```

2. Open Docker Desktop, go to **Images**, and run `feedback-analysis-agents`.
3. In **Environment variables**, add:

```text
GEMINI_API_KEY=your_api_key_here
```

Docker Desktop does not automatically read the local `.env` file when launching from the UI, so copy the same key value from `.env` into the environment variable field.

4. In **Volumes**, add this bind mount:

```text
Host path: /(put your folder directory here)/feedback_analysis_agents
Container path: /app/feedback_analysis_agents
```

Use read/write access. This lets generated files such as `outputs/processed_feedback.csv`, `outputs/clustered_feedback.csv`, and `outputs/final_tickets.csv` appear in the local `outputs/` folder.

Notes:

- Run the script from the repository root so the relative workbook and output paths resolve correctly.
- Running `main.py` calls Gemini, so it requires network access and a valid API key.
- The main knobs are `n_clusters` in `main.py`, the batch sizes in `main.py`, `MODEL_NAME` in `workflow.py`, and the prompt templates in `prompts.py`.

## Limitations
- The number of LLM calls depend on the effectiveness of the TF-IDF clustering process. If the TF-IDF is not effective, more LLM calls for the validator agent are required to process the feedback deemed by the summarizer agent that requires reconsideration.
- There is no hand-labeled gold dataset yet, so quality is currently assessed by manual inspection rather than automated precision/recall.
- KMeans require hyperparameter tuning of number of clusters (i.e. n_clusters), so this additional step is necessary for proper optimisation.
- The pipeline depends on model outputs being valid JSON. There is some parsing fallback, but production use would need stricter validation, retries, and schema checks.

- The project has a basic Dockerfile, but does not yet have CI or a formal test suite.
- By nature of grouping, certain ticket descriptions are more elaborate/broad

## Further Improvements

This prototype uses a free-tier model setup (i.e. gemini-3.1-flash-lite), so the workflow is intentionally conservative about prompt size, number of calls, and the amount of context sent to the model. With a more advanced model, larger context window, and higher rate limits, I would try larger prompts that include more cross-cluster context during summarization so the agent can avoid creating overlapping tickets earlier in the pipeline. I would also test a final global review pass where the model sees all candidate tickets, representative feedback examples, and owner assignments at once.

Other improvements worth trying:

- Use structured output or schema validation so model responses are guaranteed to match the expected JSON shape.
- Add a labeled evaluation set and tune `n_clusters`, validation batch size, and merge strictness against objective metrics.
- Use stronger embeddings or retrieval to preselect likely duplicate tickets before calling the merging agent.
- Add confidence scores and route low-confidence clusters to manual review.
- Standardize output columns and make final ticket owner assignment consistent after merging.
- Add retries, logging, cost tracking, and CI tests before treating the pipeline as deployable.

## Deployment Considerations

In production, this would likely run as a scheduled internal batch job owned by product operations, customer support operations, or an analytics engineering team. A small container or workflow runner is enough for the local compute: TF-IDF and KMeans over thousands of short feedback records should fit comfortably on one CPU with modest memory. The main cost is inference. The current design makes one Gemini call per cluster summary, one call per reconsideration batch, and one call per ticket-merge batch, with optional embedding calls if enabled. At 1,000 feedback records, that is usually tens to low hundreds of model calls depending on batch sizes and cluster count. Moreover, there are many parameters that are intentionally defined (e.g. clusters, batch sizes for each agent) so that the number of API calls can be explicitly controlled.

Once live, I would monitor JSON parse failure rate, model latency, API spend, cluster size distribution, duplicate ticket rate, human override rate, owner assignment accuracy, and drift in common issue themes. The specific risk that would keep me up at night is silent over-merging: unrelated customer pain points could be collapsed into one plausible-sounding ticket, causing a real production issue to be hidden instead of escalated.
