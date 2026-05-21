
import os
import json
import math
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from google import genai
# from openai import OpenAI
from workflow import load_feedback_data, cluster_feedback, summarise_cluster_with_gemini,  validate_with_gemini, embedding_feedback,merge_tickets


def run_feedback_workflow():
    """
    Run the full feedback-to-ticket agentic workflow.

    Output files:
        outputs/clustered_feedback.csv: the feedback of each customer alongside their assigned clusters
        outputs/final_tickets.csv: the final output of the agentic workflow,
        comprising tickets tagged with the relevant customer ids and the
        department/owner that the ticket is being sent to
    """
    print("[run_feedback_agent] Starting feedback analysis workflow")

    os.makedirs("outputs", exist_ok=True)
    print("[run_feedback_agent] Ensured outputs directory exists")

    print("[run_feedback_agent] Step 1/6: loading feedback data")
    feedback_df = load_feedback_data()
    print(f"[run_feedback_agent] Loaded feedback rows: {len(feedback_df)}")
    


    

    print("[run_feedback_agent] Step 2/6: creating first-pass clusters")

    # the embedding here is used as an alternative for the TF-IDF clustering process. 
    # After testing, it does not perform as well as TF-IDF for clustering, so this is commented out as an alternative
    '''
    feedback_to_embed=list(feedback_df["feedback"])
    related=embedding_feedback(feedback_to_embed,threshold=0.85)
    print(related)
    '''
     
    feedback_df = cluster_feedback(
        feedback_df=feedback_df,
        n_clusters=9
    )

    
    feedback_df.to_csv("outputs/clustered_feedback.csv", index=False)
    print("[run_feedback_agent] Saved outputs/clustered_feedback.csv")


    final_cluster_ids = sorted(feedback_df["cluster_id"].unique())
    print(
        "[run_feedback_agent] Step 5/6: summarising clusters and drafting tickets: "
        f"clusters={len(final_cluster_ids)}"
    )

    # reconsider_id_list contains all customers ids whose feedback is deemed by the LLM to be an "outlier" in their respective cluster
    # hence these ids and their respective feedback will be sent to the validator agent for reorganisation (put in reconsider_df)
    reconsider_id_list=[]
    ticket_info_list=[]
    df = pd.DataFrame(columns=["list of ids","ticket info", "recommended owner"])

    for cluster_position, cluster_id in enumerate(final_cluster_ids, start=1):
        cluster_df = feedback_df[feedback_df["cluster_id"] == cluster_id]
        print(
            "[run_feedback_agent] Processing cluster: "
            f"{cluster_position}/{len(final_cluster_ids)}, "
            f"cluster_id={int(cluster_id)}, rows={len(cluster_df)}"
        )

        cluster_summary = summarise_cluster_with_gemini(cluster_df)

        reconsider_ids, ticket_info, source_ids= cluster_summary["reconsider_ids"], cluster_summary["theme"]+ " : "+cluster_summary["user_pain_point"], cluster_summary['source_feedback_ids']
        recommended_owner=cluster_summary["recommended_owner"]

        accurate_ids=[id for id in source_ids if id not in reconsider_ids]

        df.loc[len(df)]=[accurate_ids, ticket_info, recommended_owner]

        reconsider_id_list.extend(reconsider_ids)

        ticket_info_list.append(ticket_info)

    reconsider_df=feedback_df.loc[feedback_df["feedback_id"].isin(reconsider_id_list), ["feedback_id","feedback"]]
    print(f"LENGTH OF RECONSIDER_DF: {len(reconsider_df)}")

    for i in range(len(ticket_info_list)):
        ticket_info_list[i]={"ticket id": i, "description":ticket_info_list[i]}

    batch_size=7
    all_assignments=[]
    for i in range(0,len(reconsider_df),batch_size):
        batch_df= reconsider_df.iloc[i:i + batch_size]

        feedback_records = [
        {
            "cust_id": row["feedback_id"],
            "feedback": row["feedback"]
        }
        for _, row in batch_df.iterrows()
    ]
        
        assignments=validate_with_gemini(feedback_records,ticket_info_list)
        
        all_assignments.extend(assignments["assignments"])

    for cust_dict in all_assignments:
        cust_id = cust_dict["cust_id"]
        if "new_ticket_info" in cust_dict.keys():
            new_ticket_info=cust_dict["new_ticket_info"]
        if "recommended_owner" in cust_dict.keys():
            recommended_owner=cust_dict["recommended_owner"]


        if cust_dict["action"]=="assign_existing_ticket":
            print("ASSIGN TO EXISTING TICKET")
            ticket_id=cust_dict["assigned_ticket_id"]
            df.at[ticket_id, "list of ids"].append(cust_id)

        elif cust_dict["action"]=="create_new_ticket":
            print("CREATE NEW TICKET")
            df.loc[len(df)]=[[cust_id,], new_ticket_info, recommended_owner]


    
    # ticket batch size refers to the number of tickets being processed by the LLM in one API call
    # this is used to control the prompt size
    ticket_batch_size=15
    all_merged_tickets=[]
    df=df.reset_index(drop=True)
    df["ticket_id"]=df.index
    for i in range(0,len(df),ticket_batch_size):
        ticket_df=df.iloc[i:i + ticket_batch_size]
        ticket_list,id_list=list(ticket_df["ticket info"]),list(ticket_df["ticket_id"])
        ticket_list=[{"ticket_id":ticket_id,"description":description} for description,ticket_id in zip(ticket_list,id_list)]
        

        merged_tickets = merge_tickets(ticket_list)
        all_merged_tickets.extend(merged_tickets["similar_tickets"])
        
    
    final_df=pd.DataFrame(columns=["list of ids","ticket info","recommended_owner"])
    merged_indexes=[]
    for ticket in all_merged_tickets:
        ticket_name, ticket_ids=ticket["merged_ticket_name"],ticket["ticket_ids"]

        merged_indexes.extend(ticket_ids)
        recommended_owner=df.iloc[ticket_ids[0]]["recommended owner"]

        all_custids=df.loc[df["ticket_id"].isin(ticket_ids),"list of ids"].explode().dropna().tolist()
        final_df.loc[len(final_df)]={
            "list of ids": all_custids,
            "ticket info": ticket_name,
            "recommended_owner": recommended_owner
        }
    non_merged_df=df.loc[
    ~df["ticket_id"].isin(merged_indexes),
    ["list of ids","ticket info","recommended owner"]
    ]

    final_tickets_df=pd.concat([final_df,non_merged_df],ignore_index=True)
    final_tickets_df.to_csv("outputs/final_tickets.csv", index=False)
    print("[run_feedback_agent] Saved outputs/final_tickets.csv")


    # Note that outputs/final_tickets.csv contains the final tickets to be sent to the relevant departments, and will be used for evaluation
    # Since human evaulation/manual inspection is being used here, and evaluation is the final step of the workflow, additional code is not necessary
    # More details on the evaluation and reasoning (e.g. human eval vs llm-as-a-judge etc) is found in the PROCESS.md file
    
        



run_feedback_workflow()
