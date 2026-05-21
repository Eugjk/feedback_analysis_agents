# Process

This project was built as a prototype for turning raw customer feedback into ticket-ready product and engineering issues. I used synthetic data deliberately because real customer support text can contain personal information, account details, and confidential product context. The synthetic workbook keeps the project shareable while still exercising realistic workflows: short support tickets, longer customer emails, and survey comments with an ease-of-use score.



## What I Tried

I started with a straightforward pandas ingestion step that reads the three Excel sheets, normalizes source labels, preserves survey scores, and assigns `feedback_id` values so every ticket recommendation can point back to evidence.

For grouping I used TF-IDF with English stopwords and 1-2 grams, followed by KMeans. This was kept because it is cheap, understandable, and easy to inspect on a small dataset. It gives the later agents a smaller, more focused set of records instead of asking an LLM to reason over every feedback item at once.

I also tried embedding each feedback point, but it turned out to be not as effective as TF-IDF during manual inspection and evaluation, which surprised me, even after varying the cosine similarity thresholds a lot, and so I stuck with TF-IDF. This is interesting enough to warrant further investigation.

I then split the LLM work into three agents. The summarizer agent turns each TF-IDF cluster into a ticket-ready issue and identifies anomalous feedback. The validation agent handles those anomalies so weak cluster assignments do not silently pollute the ticket list. The merging agent runs after validation because duplicate tickets are easier to detect once the candidate tickets have been cleaned up.

The main reason for this agentic workflow is API efficiency, not just architectural style. A single LLM agent over raw feedback would either need a very large prompt or repeated calls for many individual records. The staged design lets local TF-IDF do the cheap narrowing first, then uses LLM calls at higher-leverage points: one summarization call per cluster, validation only for uncertain records, and merging only over candidate tickets. The product goal is therefore twofold: minimize API calls per feedback item and minimize the number of final tickets a human team has to triage. Low API usage keeps the system cheaper and easier to scale; low ticket count reduces duplicate backlog noise while still preserving feedback IDs for auditability.



## What I Dropped Or Deferred

I did not use a one-shot prompt over all feedback because it would be harder to trace decisions and easier for the model to skip records. I also deferred a pure embedding clustering pipeline due to performance reasons (as mentioned above), and deferred automatic cost tracking, 




## Tools Used

- pandas for Excel and CSV processing
- scikit-learn for TF-IDF vectorization and KMeans clustering
- Gemini generation for summarization, validation, and ticket merging using gemini-3.1-flash-lite
- Gemini embeddings for semantic similarity experiments (although not in main workflow)
- Prompt templates in `prompts.py` to make model behavior explicit and editable
- Local CSV/JSON artifacts for inspection after each stage

## Judgment Calls

The most important judgment call was to use synthetic data. The project is about workflow quality, not proving a production data claim, and synthetic feedback avoids mishandling real user information. I made the data multi-channel (e.g. surveys/emails/support tickets) to create realistic variation in length and tone.

Another judgment call was to combine classical NLP with LLM reasoning. TF-IDF/KMeans gives a cheap first-pass structure, while Gemini handles ticket phrasing and edge cases. That is more transparent and usually more cost-efficient than asking the model to do all grouping in one pass. This also reduces the number of total API calls compared to a pure agentic workflow, which is also one of the main objectives.

I also chose to keep `feedback_id` values in every stage. This matters because a human reviewer should be able to audit why a ticket exists and which records support it.

## Evaluation

The evaluation is done with 2 stages: Testing of the TF-IDF + clustering process and of the agentic workflow itself. For the TF-IDF + clustering, we use the number of reconsider_ids produced by the summarizer agent as a metric, while we use ticket quality checking for the agentic workflow as a metric.

As mentioned, the summariser agent extracts the most common problem that is described in the cluster of many feedback points, and flags out the feedback in said cluster that is considered unrelated to said problem. However, we can also strategically use the output of this agent as a measure of the purity of the cluster. If the cluster is pure (i.e. each feedback point mentions the exact same user problem), then the agent will not flag out any feedback, and hence the greater the purity, the less feedback will be flagged as needing to be reconsidered. This provides a qualitative measure in addition to the usual Within cluster Sum of Squares (WCSS) metric used for K-means clustering, and is arguably more reliable, as it measures the effectiveness of both the TF-IDF and clustering process.

Current results show ~25 feedback points (out of 50) needing to be reconsidered across all clusters on average, tested using n_clusters=6,7,8,9. This can be further improved via further tuning.

The evaluation for the agentic workflow in terms of ticket quality is a mixed quantitative and qualitative review by manual inspection because the system performs clustering, classification, generation, and deduplication. A single metric would miss important failure modes.


Ticket quality was evaluated using the below criteria:

- **Groundedness:** each ticket should be clearly supported by the original feedback rows.
- **Coverage:** important user problems in the feedback should be represented in the final ticket set.
- **Actionability:** the ticket should be specific enough for a product or engineering team to investigate.
- **Scope:** each ticket should describe one coherent issue rather than mixing unrelated problems.
- **Deduplication quality:** similar feedback should be merged into one ticket, while distinct issues should not be over-merged.



The results show that the tickets being drafted are generally accurate in the coverage and groundedness aspects. Moreover, the proper "noise" being introduced is being effectively filtered out. (e.g. Consider id "F037" with the feedback "I like the clean layout and the booking flow was easy to understand." Note that this is a strictly positive feedback point with no mentions of problems needing to be solved, and hence there is no need for any ticket to be drafted.)

However, the actionability aspects need some work, as tickets with larger associated groups of ids have more broad ticket descriptions, which might not be specific enough to be considered a valid ticket, but it also depends on certain business constraints/requirements as to its validity. Some examples are: "Application Stability and Crashes", "Login and Authentication Failures".

In future evaluation practices, with a labeled sample in place, clustering can be evaluated with adjusted Rand index, or normalized mutual information. Ticket assignment and reconsideration decisions can be evaluated with precision, recall, and F1. Owner assignment can be measured as simple accuracy against the gold labels.

Moreover, generated ticket quality should also be evaluated with a human rubric that scores specificity, actionability, correct scope, evidence coverage, and whether the recommended owner is plausible. Merge quality should be reviewed separately because over-merging is more dangerous than under-merging; precision should matter more than recall for duplicate-ticket merges.


For the current synthetic dataset, the next step should be to create a hand-labeled gold file with expected issue category, expected owner, whether the feedback should create a ticket, and which final ticket it should map to. Because this project is still a small-scale prototype, the evaluation should be treated as directional rather than statistically conclusive. The goal at this stage is to identify obvious quality gaps and validate whether the workflow is useful enough to justify a larger evaluation set.

LLM-as-a-judge could be used as a secondary signal for consistency, but it should not be the primary evaluator. The project is meant to support operational decisions, so human-labeled examples and regression cases are the right basis for judging quality.
