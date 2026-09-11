import datetime
import os
import logging
import uuid
from dashvector import Client, DashVectorException, Doc
from config.nacos.nacos_service import config

from util.fix_fields import FIX_FIELDS


# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

dtype_convert = {
    'int': int,
    'float': float,
    'bool': bool,
    'str': str
}

collection_name = os.environ.get('COLLECTION_NAME', "text2sql_domain_fields_data")


ali_config = config.get('ali_vector_config', {})

ali_client = Client(
    api_key=ali_config['api_key'],
    endpoint=ali_config['endpoint']
)



def insert_data_batch(collection, batch):
    try:
        rsp = collection.insert(batch)
        if not rsp:
            raise DashVectorException(rsp.code, reason=rsp.message)
        return len(rsp.output)
    except Exception as e:
        logging.error(f"Error inserting batch : {str(e)}")



def insert_data(collection, data_list):
    try:
        insert_data_batch(collection, data_list)

    except Exception as e:
        logging.error(f"Error : {str(e)}")


def assemble_data():
    from util.rag_helpers import text_to_vectors
    data_list = []
    for table_name, columns in FIX_FIELDS.items():
        for column in columns:
            uuid_value = uuid.uuid4()  # 生成一个随机的 UUID

            # 获取当前时间的字符串时间戳
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化为字符串
            from util.rag_helpers import text_to_vectors_http
            vector = text_to_vectors(column)
            # 构建字典
            dict_data = {
                "table_name": table_name,  # 示例表名
                "field_name": column,  # 示例列名
                "time": current_time  # 当前时间的字符串时间戳
            }
            doc = Doc(id=str(uuid_value), vector=vector, fields=dict_data)
            data_list.append(doc)
    return data_list




def assemble_sec_domain_data():
    from service.sql_generator.text_to_sql_generator import embedding_sec_data

    dict = embedding_sec_data()
    data_list = []

    try:
        # 遍历 dict 中的所有表
        for table_name, table_data in dict.items():
            if table_name[-1] == '0':
                table_name = table_name[:-1]  # 去掉最后一位
            for field_name, field_item in table_data.items():
                for sec_name, sec_item in field_item.items():
                    for stockholder_name, vector in sec_item.items():
                        uuid_value = uuid.uuid4()  # 生成一个随机的 UUID
                        # 获取当前时间的字符串时间戳
                        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化为字符串

                        dict_data = {
                            "table_name": table_name,  # 使用当前表名
                            "sec_name": sec_name,
                            "field_name": field_name,  # 示例列名
                            "field_value": stockholder_name,  # 当前时间的字符串时间戳
                            "time": current_time
                        }
                        print(dict_data)
                        doc = Doc(id=str(uuid_value), vector=vector, fields=dict_data)
                        data_list.append(doc)
        return data_list
    except Exception as e:
        print(f"异常: {e}")

def assemble_domain_data():
    from service.sql_generator.text_to_sql_generator import embedding_data

    dict = embedding_data()
    data_list = []

    try:
        # 遍历 dict 中的所有表
        for table_name, table_data in dict.items():
            for field_name, field_item in table_data.items():
                    for stockholder_name, vector in field_item.items():
                        uuid_value = uuid.uuid4()  # 生成一个随机的 UUID
                        # 获取当前时间的字符串时间戳
                        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化为字符串

                        dict_data = {
                            "table_name": table_name,  # 使用当前表名
                            "field_name": field_name,  # 示例列名
                            "field_value": stockholder_name,  # 当前时间的字符串时间戳
                            "time": current_time
                        }
                        print(dict_data)
                        doc = Doc(id=str(uuid_value), vector=vector, fields=dict_data)
                        data_list.append(doc)
        return data_list
    except Exception as e:
        print(f"异常: {e}")




def insert_data_batch_size(collection, data_list):
    batch_size = 400  # 每批插入的文档数量限制
    for i in range(0, len(data_list), batch_size):
        batch = data_list[i:i + batch_size]  # 获取当前批次的数据

        try:
                rsp = collection.insert(batch)
                print(f"Batch {i // batch_size + 1} inserted successfully.")
                if not rsp:
                    raise DashVectorException(rsp.code, reason=rsp.message)
        except Exception as e:
                logging.error(f"Error inserting batch : {str(e)}")
                print(f"Batch {i // batch_size + 1} inserted successfully.")



if __name__ == "__main__":
    data_list=assemble_sec_domain_data()
    print(len(data_list))
    collection = ali_client.get("text2sql_sec_domain_fields_data")
    #
    # # 顺序处理文件
    insert_data_batch_size(collection,data_list)


    data_list=assemble_domain_data()
    print(len(data_list))
    collection = ali_client.get("text2sql_domain_fields_data")
    # # 顺序处理文件
    insert_data_batch_size(collection,data_list)