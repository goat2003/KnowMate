from datetime import datetime

from app.DBserver.mongoDB_repository.mongoDB_repository import BaseRepository

class MongoDBServer():
    def __init__(self):
        self.mongodb_repository = BaseRepository("test")



if __name__ == "__main__":
    mongodb_server = MongoDBServer()
    index = [("role_id", 1), ("Q_id", 1)]
    # mongodb_server.mongodb_repository.create_unique_indexes(index)
    data = {
        "role_id": 1,
        "Q_id": 1,
        "info": "ysdc",
        "status": 1,
        "create_time": datetime.now()
    }

    result = mongodb_server.mongodb_repository.insert_one(data)
    # print(result)
    data_list = [
        {
            "role_id": 1,
            "Q_id": 1,
            "info": "a",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 1, 15, 23)
        },
        {
            "role_id": 2,
            "Q_id": 1,
            "info": "b",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 4, 28, 11)
        },
        {
            "role_id": 3,
            "Q_id": 1,
            "info": "c",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 9, 42, 57)
        },
        {
            "role_id": 4,
            "Q_id": 1,
            "info": "d",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 13, 5, 44)
        },
        {
            "role_id": 5,
            "Q_id": 1,
            "info": "e",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 18, 37, 29)
        },
        {
            "role_id": 6,
            "Q_id": 1,
            "info": "f",
            "status": 1,
            "create_time": datetime(2026, 5, 12, 22, 14, 8)
        },
        {
            "role_id": 7,
            "Q_id": 1,
            "info": "g",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 2, 9, 31)
        },
        {
            "role_id": 8,
            "Q_id": 1,
            "info": "h",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 6, 51, 12)
        },
        {
            "role_id": 9,
            "Q_id": 1,
            "info": "i",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 10, 23, 49)
        },
        {
            "role_id": 10,
            "Q_id": 1,
            "info": "j",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 14, 47, 5)
        },
        {
            "role_id": 11,
            "Q_id": 1,
            "info": "k",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 18, 16, 40)
        },
        {
            "role_id": 12,
            "Q_id": 1,
            "info": "l",
            "status": 1,
            "create_time": datetime(2026, 5, 13, 21, 58, 17)
        },
        {
            "role_id": 13,
            "Q_id": 1,
            "info": "m",
            "status": 1,
            "create_time": datetime(2026, 5, 14, 1, 26, 54)
        },
        {
            "role_id": 14,
            "Q_id": 1,
            "info": "n",
            "status": 1,
            "create_time": datetime(2026, 5, 14, 7, 43, 20)
        },
        {
            "role_id": 15,
            "Q_id": 1,
            "info": "o",
            "status": 1,
            "create_time": datetime(2026, 5, 14, 10, 58, 41)
        }
    ]

    # mongodb_server.mongodb_repository.insert_many(data_list)

    # query 根据时间查询
    start_time = datetime(2026, 5, 12, 0, 0, 0)

    end_time = datetime(2026, 5, 13, 0, 0, 0)

    query={
        "create_time": {
            "$gte": start_time,
            "$lt": end_time
        }
    }

    result1 = mongodb_server.mongodb_repository.query_many(
        query,
        # projection: 只获取 info 的信息
        projection={
            "info": 1
        }
    )
    print(result1)
    # [{"_id": , "info": }]

    result2 = mongodb_server.mongodb_repository.delete_many(query)
    print(result2)

    query = {"role_id": "1", "questionnaire_id": "3"}
    projection = {"status": 1}
    status = mongodb_server.mongodb_repository.query_one(
        query,
        projection
    )
    print("status: ", status)
