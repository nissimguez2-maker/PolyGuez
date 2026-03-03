from typing import Optional

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}


@app.get("/trades/{trade_id}")
def read_trade(trade_id: int, q: Optional[str] = None):
    return {"trade_id": trade_id, "q": q}


@app.get("/markets/{market_id}")
def read_market(market_id: int, q: Optional[str] = None):
    return {"market_id": market_id, "q": q}


# post new prompt
