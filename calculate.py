#!/usr/bin/env python

import asyncio
import websockets
import json
import requests
import logging
from  logging.handlers import TimedRotatingFileHandler
import time
import numpy as np
import hmac
import hashlib
import os
import sys
import random
from exchange.poloniex import poloniexUtil
from exchange.okex import okexUtil
from exchange.bitfinex import bitfinexUtil
from datetime import datetime
import sqlite3
SUPPORT_PAIR='ETC_USDT'
if 'pair' in os.environ:
	SUPPORT_PAIR=os.environ['pair']
logger = logging.getLogger("deal")
logger.setLevel(logging.DEBUG)
ch = TimedRotatingFileHandler(SUPPORT_PAIR+'.log', when='D', interval=1, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

logger.info('BEGIN monitor {}'.format(SUPPORT_PAIR))
okexUtil=okexUtil(SUPPORT_PAIR)
poloniexUtil=poloniexUtil(SUPPORT_PAIR)
bitfinexUtil=bitfinexUtil(SUPPORT_PAIR)
exchanges=[okexUtil,poloniexUtil,bitfinexUtil]
MINIST_VALUE=-999999
exch1_exch2_max=MINIST_VALUE
exch2_exch1_max=MINIST_VALUE
exch1_exch2_lst=[]
exch2_exch1_lst=[]
SAMPLE_INTERVAL=1
PERIORD=3*60*60
REPORT_INTERVAL=60
INSERT_SQL='insert into  bookOrder (diversion,timestamp,exchange,type) values(?,?,?,?)'
CREATE_SQL='CREATE TABLE IF NOT EXISTS bookOrder (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,diversion real,timestamp INTEGER,exchange text,type INTEGER)'
COMBINATION=[(0,1),(1,0),(0,2),(1,2),(2,0),(2,1)]
ENABLE_TRADE_MODIFY=0
if 'enable_trade_modify' in os.environ:
	ENABLE_TRADE_MODIFY=1

async def trade_handler():
	try:
		global COMBINATION
		global exchanges
		local_diff_max=-99999
		local_exchange_pair=None
		for item in COMBINATION:
			if exchanges[item[0]].ticker_data is None or exchanges[item[1]].ticker_data is None:
				continue
			diff = exchanges[item[0]].ticker_data[1] 
					- exchanges[item[1]].ticker_data[0]
					-exchanges[item[0]].ticker_data[1]*exchanges[item[0]].TAKER_FEE
					-exchanges[item[1]].ticker_data[0]*exchanges[item[1]].TAKER_FEE

			if diff>localMax:
				local_exchange_pair = item
				localMax=diff
			
	except Exception as e:
		logger.error("Trade_handler_error:{}".format(e))
async def sampler():
	global exch1_exch2_max
	global exch2_exch1_max
	global MINIST_VALUE
	global SUPPORT_PAIR
	while True:
		await asyncio.sleep(SAMPLE_INTERVAL)
		logger.info('sample record {},{}'.format(exch1_exch2_max,exch2_exch1_max))
		exch1_exch2_lst.append(exch1_exch2_max)
		exch2_exch1_lst.append(exch2_exch1_max)
		
		dbFile = 'orderbook_'+SUPPORT_PAIR+'_'+datetime.now().strftime("%Y-%m-%d")+'.db'
		conn = sqlite3.connect(dbFile)
		cursor = conn.cursor()
		cursor.execute(CREATE_SQL)		
		lst=[]
		ts= int(time.time())
		lst.append((exch1_exch2_max,ts,'ok_polo',0))
		lst.append((exch2_exch1_max,ts,'ok_polo',1))
		cursor.executemany(INSERT_SQL,lst)
		cursor.connection.commit()
		conn.close()
		exch1_exch2_max=MINIST_VALUE
		exch2_exch1_max=MINIST_VALUE

async def percentile():
	while True:
		global exch1_exch2_lst
		global exch2_exch1_lst
		await asyncio.sleep(REPORT_INTERVAL)
		logger.debug('percentile length:{},{}'.format(len(exch1_exch2_lst),len(exch2_exch1_lst)))
		enable=len(exch1_exch2_lst)>PERIORD
		if len(exch1_exch2_lst)> PERIORD:
			exch1_exch2_lst=exch1_exch2_lst[-PERIORD:]
		if len(exch2_exch1_lst) > PERIORD:
			exch2_exch1_lst=exch2_exch1_lst[-PERIORD:]
		logger.debug('percentile after length:{},{}'.format(len(exch1_exch2_lst),len(exch2_exch1_lst)))
		rg=[99.9,99.8,99.7,99.6,99.5,99.5,99.4,99.3,99.2,99.1,99,98,97,96,95,90,80]
		for item in rg:
			logger.info('REPORT RES {} exch1_buy:{}, exch2_buy:{}'.format(item,np.percentile(exch1_exch2_lst,item),np.percentile(exch2_exch1_lst,item)))
		global ENABLE_TRADE_MODIFY
		if ENABLE_TRADE_MODIFY==1 and enable:
			params={}
			ok_buy_thres=np.percentile(exch1_exch2_lst,99.9)
			poloniex_buy_thres=np.percentile(exch2_exch1_lst,99.9)
			if ok_buy_thres+poloniex_buy_thres >0.05:
				params['ok_buy_thres']=ok_buy_thres
				params['poloniex_buy_thres']=poloniex_buy_thres
				params['rand']=str(random.randint(1000000,2000000))
				randStr='I am really poor'+params['rand']
				params['sign']=hmac.new(randStr.encode(),digestmod=hashlib.sha256).hexdigest()
				r = requests.post("http://45.62.107.169:20183/threshold", data=json.dumps(params))
				logger.info('FINISH update:{}'.format(r.text))


async def deal_handler():
	return await asyncio.wait([poloniexUtil.order_book(trade_handler),okexUtil.order_book(trade_handler),sampler(),percentile()],return_when=asyncio.FIRST_COMPLETED,)

loop=asyncio.get_event_loop()
loop.run_until_complete(deal_handler())
