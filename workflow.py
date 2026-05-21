

import os
import json
import math
import pandas as pd
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
from google import genai
from google.genai import types
import numpy as np
from prompts import  VALIDATOR_PROMPT,SUMMARY_PROMPT,MERGER_PROMPT
print("imports done")
load_dotenv()

excel_filepath="../feedback_analysis_agents/synthetic_online_app_feedback_datasets.xlsx"
MODEL_NAME = "gemini-3.1-flash-lite"

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


CLUSTER_SIZE_THRESHOLD = 20
RANDOM_STATE = 42


def load_feedback_data(
        excel_path: str=excel_filepath
):
    """
    Load the three synthetic feedback datasets and standardise them into one dataframe.

    Returns:
        pd.DataFrame: Combined dataframe with columns:
            - feedback_id
            - cust_id
            - source
            - feedback
            - ease_of_use_score
    """
    

    support_df = pd.read_excel(excel_path, sheet_name=0)
    email_df = pd.read_excel(excel_path, sheet_name=1)
    survey_df = pd.read_excel(excel_path, sheet_name=2)
    

    support_df["source"] = "customer_support_ticket"
    email_df["source"] = "email"
    survey_df["source"] = "survey"
    

    support_df["ease_of_use_score"] = None
    email_df["ease_of_use_score"] = None
    

    combined_df = pd.concat(
        [support_df, email_df, survey_df],
        ignore_index=True
    )
    

    combined_df = combined_df.dropna(subset=["cust_id", "feedback"])
    
    combined_df["feedback_id"] = [
        f"F{i + 1:03d}" for i in range(len(combined_df))
    ]
    

    combined_df = combined_df[
        ["feedback_id", "cust_id", "source", "feedback", "ease_of_use_score"]
    ]

    os.makedirs("outputs", exist_ok=True)
    combined_df.to_csv("outputs/processed_feedback.csv", index=False)
    print("[load_feedback_data] Saved outputs/processed_feedback.csv")

    return combined_df

processed_data = load_feedback_data(excel_filepath)


def cluster_feedback(feedback_df, n_clusters):
    """
    Group similar feedback using a simple TF-IDF + KMeans approach.

    This keeps the first version lightweight and avoids needing an embedding API.

    Args:
        feedback_df (pd.DataFrame): Combined feedback dataframe.
        n_clusters (int): Number of clusters to form.

    Returns:
        pd.DataFrame: Feedback dataframe with an added cluster_id column.
    """
    print(
        "[cluster_feedback] Starting first-pass clustering: "
        f"rows={len(feedback_df)}, target_clusters={n_clusters}"
    )

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=1000,
        ngram_range=(1, 2)
    )

    print("[cluster_feedback] Vectorising feedback text with TF-IDF")
    x = vectorizer.fit_transform(feedback_df["feedback"])
    print(
        "[cluster_feedback] TF-IDF matrix ready: "
        f"rows={x.shape[0]}, features={x.shape[1]}"
    )

    model = KMeans(
        n_clusters=n_clusters,
        #random_state=RANDOM_STATE,
        n_init="auto"
    )

    print("[cluster_feedback] Fitting KMeans model")
    feedback_df["cluster_id"] = model.fit_predict(x)
    cluster_sizes = feedback_df["cluster_id"].value_counts().sort_index().to_dict()
    print(f"[cluster_feedback] First-pass clustering done: sizes={cluster_sizes}")

    return feedback_df

# note that this is used as a possible alternative for TF-IDF, but not used in the main workflow
def embedding_feedback(list_to_embed,threshold):
    """
    Embed feedback text and group semantically similar items.

    This function sends the provided feedback strings to Gemini's embedding model,
    converts the returned embeddings into a NumPy matrix, and computes pairwise
    cosine similarity across all feedback items. Feedback items are treated as
    related when their similarity score is greater than or equal to `threshold`.

    Related items are grouped using depth-first search over the similarity graph:
    each feedback item is a node, and an edge exists between two nodes when their
    cosine similarity meets the threshold. The function returns only groups with
    more than one item, so standalone feedback items are intentionally omitted.

    Args:
        list_to_embed (list[str]): Feedback text values to embed and compare.
        threshold (float): Minimum cosine similarity score required for two
            feedback items to be considered related.

    Returns:
        list[tuple[int, ...]]: Groups of related feedback item indices. Each
        index refers to the original position of that feedback item in
        `list_to_embed`.
    """
    result = client.models.embed_content(
    model="gemini-embedding-001",
    contents=list_to_embed,
    config=types.EmbedContentConfig(
        task_type="CLUSTERING"
    )
)
    embeddings=[e.values for e in result.embeddings]
    x = np.array(embeddings)

    # Compute pairwise cosine similarity
    sim_matrix = cosine_similarity(x)

    n = len(embeddings)
    visited = set()
    related_groups = []

    def dfs(i, current_group):
        """
        Depth-first search to collect all embeddings connected to i.
        """
        visited.add(i)
        current_group.append(i)

        for j in range(n):
            if j not in visited and i != j:
                if sim_matrix[i][j] >= threshold:
                    dfs(j, current_group)

    for i in range(n):
        if i not in visited:
            current_group = []
            dfs(i, current_group)

            # Only keep groups with at least 2 related embeddings
            if len(current_group) > 1:
                related_groups.append(tuple(current_group))

    

    return related_groups
    



def parse_json_response(response_text):
    """
    Parse a JSON response returned by the LLM.

    LLM responses sometimes include extra formatting around the JSON, especially
    Markdown code fences such as ```json ... ```. This helper first strips empty
    input and removes any fenced-code wrapper so the remaining text can be parsed
    as JSON.

    The function then tries to parse the cleaned text directly with
    `json.loads()`. If that fails, it attempts a fallback parse by extracting the
    substring between the first opening brace and the last closing brace. This is
    useful when the model adds a short explanation before or after the JSON
    object.

    Args:
        response_text (str): Raw text returned by the model.

    Returns:
        dict | list: Parsed JSON content from the model response.

    Raises:
        json.JSONDecodeError: If neither the full cleaned response nor the
        extracted JSON-looking substring can be parsed.
    """
    text = (response_text or "").strip()

    if text.startswith("```"):
        print("[parse_json_response] Detected fenced response; removing code fences")
        text = "\n".join(
            line
            for line in text.splitlines()
            if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(text)
        print("[parse_json_response] Parsed JSON directly")
        return parsed
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and start < end:
            print("[parse_json_response] Direct parse failed; trying JSON object substring")
            parsed = json.loads(text[start:end + 1])
            print("[parse_json_response] Parsed JSON from substring")
            return parsed
        print("[parse_json_response] Failed to parse JSON response")
        raise


def normalize_cluster_summary(summary, cluster_df):
    
    source_feedback_ids = cluster_df["feedback_id"].tolist()
    valid_feedback_ids = set(source_feedback_ids)

    reconsider_ids = summary.get("reconsider_ids", [])
    if not isinstance(reconsider_ids, list):
        print("[normalize_cluster_summary] reconsider_ids was not a list; replacing with []")
        reconsider_ids = []

    summary["source_feedback_ids"] = [
        feedback_id
        for feedback_id in source_feedback_ids
        if feedback_id in valid_feedback_ids
    ]
    summary["reconsider_ids"] = [
        feedback_id
        for feedback_id in reconsider_ids
        if feedback_id in valid_feedback_ids
    ]
    summary["feedback_count"] = int(len(cluster_df))

    return summary


def summarise_cluster_with_gemini(cluster_df):
    """
    Use Gemini to summarise one cluster of similar feedback.

    Args:
        cluster_df (pd.DataFrame): Rows belonging to one feedback cluster.

    Returns:
        dict: Structured summary containing:
            - theme
            - duplicate_reason
            - user_pain_point
            - affected_sources
            - actionable_insight
            - recommended_owner
    """
    cluster_label = (
        int(cluster_df["cluster_id"].iloc[0])
        if "cluster_id" in cluster_df.columns and not cluster_df.empty
        else "unknown"
    )
    #print(  "[summarise_cluster_with_gemini] Preparing cluster summary: " f"cluster_id={cluster_label}, rows={len(cluster_df)}")

    feedback_records = cluster_df[
        ["feedback_id", "cust_id", "source", "feedback", "ease_of_use_score"]
    ].to_dict(orient="records")
    

    feedback_json = json.dumps(feedback_records, indent=2)
    #print(feedback_json)

    new_prompt = SUMMARY_PROMPT.format(feedback=feedback_json)
    print(
        "[summarise_cluster_with_gemini] Calling Gemini summarizer: "
        f"model={MODEL_NAME}, prompt_chars={len(new_prompt)}"
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=new_prompt
    )
    response_text = response.text or ""
    

    try:
        summary = parse_json_response(response_text)
        if not isinstance(summary, dict):
            raise ValueError("Model returned JSON that was not an object.")
        print("[summarise_cluster_with_gemini] Summary JSON parsed successfully")
    except (json.JSONDecodeError, ValueError):
        print("[summarise_cluster_with_gemini] Summary parsing failed; using fallback summary")
        summary = {
            "theme": "JSON parsing failed",
            "user_pain_point": response_text,
            "affected_sources": cluster_df["source"].unique().tolist(),
            "actionable_insight": "Review this cluster manually.",
            "recommended_owner": "product",
            "source_feedback_ids": cluster_df["feedback_id"].tolist(),
            "reconsider_ids": []
        }

    normalized_summary = normalize_cluster_summary(summary, cluster_df)
    print(
        "[summarise_cluster_with_gemini] Cluster summary complete: "
        f"cluster_id={cluster_label}, "
        f"reconsider_ids={len(normalized_summary['reconsider_ids'])}"
    )
    return normalized_summary

def validate_with_gemini(feedback_records, ticket_info_list):
    print("VALIDATING")
    validator_prompt=VALIDATOR_PROMPT.format(
        feedback_records=feedback_records,
        ticket_info_list=ticket_info_list
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=validator_prompt
    )
    response_text = response.text or ""
    try:
        assignments = parse_json_response(response_text)
        if not isinstance(assignments, dict):
            raise ValueError("Model returned JSON that was not an object.")
        print("[summarise_cluster_with_gemini] Summary JSON parsed successfully")
    except (json.JSONDecodeError, ValueError):
        print("[summarise_cluster_with_gemini] Summary parsing failed; using fallback summary")
        assignments={
        "cust_id": "NA",
        "action": "NA",
        "new_ticket_info": "NA",
        "recommended_owner": "NA",
        "confidence": "NA",
        }
    return assignments

    
def merge_tickets(ticket_list):

    merge_prompt=MERGER_PROMPT.format(
        tickets=ticket_list
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=merge_prompt
    )
    response_text = response.text or ""
    print(
        "MERGING TICKETS"
    )

    try:
        merged_tickets = parse_json_response(response_text)
        if not isinstance(merged_tickets, dict):
            raise ValueError("Model returned JSON that was not an object.")
        print("[merge_tickets] Merge JSON parsed successfully")
    except (json.JSONDecodeError, ValueError):
        print("[merge_tickets] Merge parsing failed; using empty merge result")
        merged_tickets = {"similar_tickets": []}

    return merged_tickets
