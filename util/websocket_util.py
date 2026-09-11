import json


async def send_response(websocket, step4, is_end=False,is_table=False,table_data=None):
    response = {
        "data": {
            "isTable":is_table,
            "answer": step4,
            "isEnd": is_end,
            "tableData":table_data
        }
    }
    await websocket.send_text(json.dumps(response))