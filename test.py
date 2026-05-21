
import pandas as pd

df=pd.read_csv("/Users/eugenegohjunkiat/Downloads/feedback_analysis_agents/check.csv")
all_merged_tickets= [{'merged_ticket_name': 'Application Crashes During User Actions', 'ticket_ids': [19, 26]}, {'merged_ticket_name': 'Chatbot Inefficiency and Query Misinterpretation', 'ticket_ids': [22, 24]}, {'merged_ticket_name': 'Feature Request for Automatic Draft Saving', 'ticket_ids': [23, 28]}]
merged_indexes=[]
final_df=pd.DataFrame(columns=["list of ids","ticket info","recommended_owner"])
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
    #print(final_df)

non_merged_df=df.loc[
    ~df["ticket_id"].isin(merged_indexes),
    ["list of ids","ticket info","recommended owner"]
    ]

x=pd.concat([final_df,non_merged_df],ignore_index=True)
print(x)

    
