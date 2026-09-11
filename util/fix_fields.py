FIX_FIELDS = {'VIEW_STI_FIN_IDX': ['INNER_CODE', 'COMCODE', 'RPT_DATE', 'STARTDATE', 'ENDDATE', 'RPT_TYPE'],
'VIEW_STI_FIN_IDX_QTR': ['COMCODE', 'RPT_DATE', 'STARTDATE', 'ENDDATE', 'RPT_TYPE'],
 'VIEW_STK_BALA_GEN': ['COMCODE', 'RPT_DATE',
  'ENDDATE',
  'RPT_TYPE',
  'A_STOCKCODE',
  'A_STOCKSNAME'],
 'VIEW_STI_BALA_GEN': ['COMCODE', 'RPT_DATE', 'ENDDATE', 'RPT_TYPE'],
 'VIEW_STK_CASH_GEN': ['COMCODE',
  'RPT_DATE',
  'STARTDATE',
  'ENDDATE',
  'RPT_TYPE',
  'A_STOCKCODE',
  'A_STOCKSNAME'],
 'VIEW_STI_CASH_GEN': ['COMCODE', 'RPT_DATE', 'STARTDATE', 'ENDDATE', 'RPT_TYPE'],
 'VIEW_STK_INCOME_GEN': ['COMCODE',
  'RPT_DATE',
  'STARTDATE',
  'ENDDATE',
  'RPT_TYPE',
  'A_STOCKCODE',
  'A_STOCKSNAME'],
 'VIEW_STI_INCOME_GEN': ['COMCODE', 'RPT_DATE', 'STARTDATE', 'ENDDATE', 'RPT_TYPE'],
 'STK_COM_PROFILE': ['COMCODE', 'CSName'],
 'VIEW_STK_INCOME_GEN_QTR': ['COMCODE',
  'RPT_DATE',
  'ENDDATE',
  'RPT_TYPE',
  'RPT_YEAR',
  'RPT_QTR',
  'A_STOCKCODE',
  'A_STOCKSNAME'],
 'ANA_STK_EXPR_IDX': ['INNER_CODE', 'ENDDATE', 'STOCKCODE', 'STOCKSNAME'],
 'ORG_PROFILE': ['OrgCode', 'CSName'],
 'STI_COM_PROFILE': ['COMCODE', 'CSNAME'],
 'HK_FINBS_NSTD': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'HK_ANA_STK_IDX_NFIN': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'HK_FINIS_NSTD': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'ANA_STI_EXPR_IDX': ['INNER_CODE', 'TRADEDATE'],
 'HK_ANA_STK_IDX_FIN': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'HK_NFINIS_NSTD': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'HK_LTTFINIDC_DIDC': ['COMUNIC'],
 'ANA_STK_QTR_IDX': ['COMCODE', 'ENDDATE', '', 'A_STOCKCODE', 'A_STOCKSNAME'],
 'STK_DIV_INFO': ['COMCODE', 'ITEM_ID', 'A_STOCKCODE', 'A_STOCKSNAME'],
 'HK_NFINBS_NSTD': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'STK_SHR_STRU': ['COMCODE', 'CHANGEDATE', 'A_STOCKCODE', 'A_STOCKSNAME'],
 'VIEW_STK_FIN_IDX': ['INNER_CODE', 'COMCODE', 'RPT_DATE', 'ENDDATE'],
 'HK_COMBINFO': ['COMUNIC', 'COMCNABB', 'COMENABB'],
 'GET_INDX_GEN_INFO': ['INNER_CODE', 'INDX_SNAME', 'SW_INDX_LEVEL'],
 'STK_ACHIEVE_FORECAST': ['COMCODE', 'ITEM_ID', 'A_STOCKCODE', 'A_STOCKSNAME'],
 'STK_MKT': ['INNER_CODE', 'TRADEDATE', 'SECCODE', 'STOCKSNAME'],
 'STK_EMP_STK_OWN_PLAN': ['COMCODE',
  'ITEM_NUM',
  'PLAN_ORG_CODE',
  'PLAN_NAME',
  'OBJ_STK_CODE',
  'OBJ_INNER_CODE'],
 'HK_CFS_NSTD': ['COMUNIC', 'EDATE', 'RPTSOUREFC'],
 'STI_DIV_INFO': ['COMCODE', 'ITEM_ID', 'SECSNAME', 'SECCODE'],
 'STK_ACHIEVE_REPORT': ['COMCODE',
  'ITEM_NUM',
  'ENDDATE',
  'A_STOCKCODE',
  'A_STOCKSNAME'],
 'HK_IDC_STKPFMIDC': ['STKUNICODE', 'EDATE'],
 'STI_MKT': ['INNER_CODE', 'TRADEDATE'],
 'STI_ACHIEVE_FORECAST': ['COMCODE', 'ITEM_NUM', 'DECLAREDATE', 'ENDDATE'],
 'STK_EQT_CHNG': ['COMCODE',
  'PERIODDATE',
  'RPT_TYPE',
  'ENDDATE',
  'ITEM_NUM',
  'A_STOCKCODE',
  'A_STOCKSNAME',
  'RPT_SRC',
  'ITEM'],
 'STI_ACHIEVE_REPORT': ['COMCODE',
  'ITEM_NUM',
  'ENDDATE',
  'DECLAREDATE',
  'ITEM_CODE'],
 'VIEW_STK_FIN_IDX_PLUS': ['COMCODE', 'INNER_CODE', 'RPT_TYPE', 'STARTDATE', 'ENDDATE', 'RPT_YEAR', 'RPT_TAG']}


DYNAMIC_TABLES = {'VIEW_STI_FIN_IDX', 'VIEW_STI_FIN_IDX_QTR', 'VIEW_STK_BALA_GEN', 'VIEW_STI_BALA_GEN', 'VIEW_STK_CASH_GEN',
       'VIEW_STI_CASH_GEN', 'VIEW_STK_INCOME_GEN', 'VIEW_STI_INCOME_GEN', 'VIEW_STK_INCOME_GEN_QTR', 'ANA_STK_EXPR_IDX',
       'ORG_PROFILE', 'STI_COM_PROFILE', 'HK_FINBS_NSTD',
       'HK_ANA_STK_IDX_NFIN', 'HK_FINIS_NSTD', 'ANA_STI_EXPR_IDX',
       'HK_ANA_STK_IDX_FIN', 'HK_NFINIS_NSTD', 'HK_LTTFINIDC_DIDC',
       'ANA_STK_QTR_IDX', 'STK_DIV_INFO', 'HK_NFINBS_NSTD',
       'STK_SHR_STRU', 'VIEW_STK_FIN_IDX', 'HK_COMBINFO', 'GET_INDX_GEN_INFO',
       'STK_ACHIEVE_FORECAST', 'STK_MKT', 'STK_EMP_STK_OWN_PLAN',
       'HK_CFS_NSTD', 'STI_DIV_INFO', 'STK_ACHIEVE_REPORT',
       'HK_IDC_STKPFMIDC', 'STI_MKT', 'STI_ACHIEVE_FORECAST',
       'STK_EQT_CHNG', 'STI_ACHIEVE_REPORT', 'VIEW_STK_FIN_IDX_PLUS'}

DEFAULT_TABLES = {'GET_A_INDUSTRY', 'GET_A_SEC_CODE', 'HK_COMBINFO', 'HK_STKCODE', 'HK_INDCHCOM', 'PUB_INDU_REF', 'GET_INDX_GEN_INFO'}


domain_task = {'主板经营':'营收拆分','主板股本股东':'股东查询','一般数据查询':'一般数据查询'}

recall_tables = {'STK_MNG_POST':('POST','高管职位','关键词示例包括：总经理、工程师、总监、首席执行官(CEO)、办公室主任等'),
                 'STK_PRI_INCOME_PRODUCT':('ITEM_NAME','主营业务中产品','关键词示例包括：互联网服务、房地产、洗衣机、网络安全产品、设备制造业务、储能电池、其他业务等'
                                                                        '- 对于类似“xx有哪些产品？xx有哪些业务？”的查询，如果查询中没有提及具体的产品或业务名称，则不应提取关键词。'
                                                                        '- 如果查询中包含了具体的产品或业务名称，则应提取这些关键词。'),
                 'STK_PRI_INCOME_DISTRICT':('ITEM_NAME','主营业务中地区','关键词示例包括:外销、海外、西南、西北、贵州、合计、内销等'
                                                                        '- 对于【xx在哪些地区有业务收入】，不应该抽取出关键词，因为这里没有具体的地区指代'),
                 'STI_PRI_INCOME_PRODUCT':('ITEM_NAME','科创板主营业务中产品','关键词示例包括：互联网服务、房地产、洗衣机、储能电池、网络安全产品、设备制造业务、其他业务等'
                                                                        '- 对于类似“xx有哪些产品？xx有哪些业务？”的查询，如果查询中没有提及具体的产品或业务名称，则不应提取关键词。'
                                                                        '- 如果查询中包含了具体的产品或业务名称，则应提取这些关键词。'),
                 'STI_PRI_INCOME_DISTRICT':('ITEM_NAME','科创板主营业务中地区','关键词示例包括：外销、海外、西南、西北、贵州、合计、内销等'
                                                                        '- 对于【xx在哪些地区有业务收入】，不应该抽取出关键词，因为这里没有具体的地区指代'),
                 'GET_STK_SHR_CLS_DTL':('NAME','股东名称/性质','关键是识别出那些持有的公司而不是被持有的公司!!!'
                                                      '- 关键词示例包括:xx公司、xx有限公司、xx基金、xx有限责任公司、人名、xx国资委、xx外资公司、xx高管、xx员工持股平台、xx合伙企业等。'
                                                      '- 对于【xx公司控股了哪些公司、xx是哪些公司的股东】的问题，提取xx公司作为关键词，因为它指的是作为股东的实体。'
                                                      '- 对于【xx公司被哪些公司控股、xx公司的股东有哪些】的问题，不提取关键词，因为这些公司是被控股的对象。'
                                                      '- 对于【xx公司控股yy公司多少】的问题，提取xx公司作为关键词，不应该提取yy公司也加到关键词里。'
                                                           '注意！！！如果作为股东的关键词是非常笼统的比如说【A股上市公司】之类的，这种是表示一个类别而非具体的股东名称，则也不抽取'
                                                      '\n## Constraints'
                                                      '- 只输出与股东相关的关键词，不输出其他无关内容。'
                                                      '- 确保关键词的提取准确，避免提取被控股的对象作为关键词。'),
                 'VIEW_COM3105':('F006V','美股业务中产品','关键词示例包括：互联网服务、房地产、洗衣机、储能电池、网络安全产品、设备制造业务、其他业务等'
                                               '- 对于类似“xx有哪些产品？xx有哪些业务？”的查询，如果查询中没有提及具体的产品或业务名称，则不应提取关键词。'
                                               '- 如果查询中包含了具体的产品或业务名称，则应提取这些关键词。'),
                 'VIEW_COM3106':('F006V','美股业务中地区','关键词示例包括:加州、德国、欧洲、美国、瑞典等国家名称'
                                                     '- 对于【xx在哪些地区有业务收入】，不应该抽取出关键词，因为这里没有具体的地区指代')}