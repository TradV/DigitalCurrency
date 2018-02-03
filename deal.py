#!/usr/bin/env python

import asyncio
import websockets
import json
import requests
import logging
from  logging.handlers import TimedRotatingFileHandler
logger = logging.getLogger("deal")
logger.setLevel(logging.DEBUG)
ch = TimedRotatingFileHandler('deal.log', when='D', interval=1, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)
import os
import sys
from exchange.poloniex import poloniexUtil
from exchange.okex import okexUtil

wallet={}
BOOK_LIMIT=5
poloniex_book={}
okex_book={}
okexUtil=okexUtil()
poloniexUtil=poloniexUtil()
loop=asyncio.get_event_loop()
async def okex():
	global okex_book
	while True:
		
		async with websockets.connect('wss://real.okex.com:10441/websocket') as websocket:
			try:

				param={'event':'addChannel','channel':'ok_sub_spot_etc_usdt_depth_5'}
				await websocket.send(json.dumps(param))
				while True:
					message = await websocket.recv()
					res=json.loads(message)
					if type(res) is list and res[0]['channel'].startswith('ok'):
						ask_map={}
						for item in res[0]['data']['asks']:
							ask_map[item[0]]=float(item[1])
						okex_book['ask']=ask_map
						bid_map={}
						for item in res[0]['data']['bids']:
							bid_map[item[0]]=float(item[1])
						okex_book['bid']=bid_map
					await makeDecision()
			except  Exception as e:
				okex_book={}
				logger.error(e)
				websocket.close()
				

async def poloniex():
	async with websockets.connect('wss://api2.poloniex.com/') as websocket:
		param={'command':'subscribe','channel':173}

		await websocket.send(json.dumps(param))

		while True:
			message = await websocket.recv()
			res=json.loads(message)
			if len(res)<2:
				continue
			for item in res[2]:
				if item[0] == 'i':
					book_size=0
					ask_map={}
					for key in sorted(item[1]['orderBook'][0],key=lambda subItem:float(subItem))[:BOOK_LIMIT]:
						ask_map[key]=float(item[1]['orderBook'][0][key])
					poloniex_book['ask']=ask_map
					bid_map={}
					for key  in sorted(item[1]['orderBook'][1],key=lambda subItem:float(subItem),reverse=True)[:BOOK_LIMIT]:
						bid_map[key]=float(item[1]['orderBook'][1][key])
					poloniex_book['bid']=bid_map
				elif item[0] == 'o':
					# ['o', 1, '26.54474428', '0.00000000']
					if item[1] == 0:#ask
						if float(item[3])==0 and item[2] in  poloniex_book['ask']:
							del poloniex_book['ask'][item[2]]
						elif float(item[3])>0:
							poloniex_book['ask'][item[2]]=float(item[3])
					elif item[1] == 1:#bid
						if float(item[3])==0 and item[2] in  poloniex_book['bid']:
							del poloniex_book['bid'][item[2]]
						elif float(item[3])>0:
							poloniex_book['bid'][item[2]]=float(item[3])
			await makeDecision()
async def handler():
	return await asyncio.wait([okex(),poloniex()],return_when=asyncio.FIRST_COMPLETED,)
def initAll():
	logger.debug('start init all')
	if 'ok_access_key' in os.environ and 'poloniex_access_key' in os.environ:
		okexUtil.access_key=os.environ['ok_access_key']
		okexUtil.secret_key=os.environ['ok_secret_key']
		poloniexUtil.access_key=os.environ['poloniex_access_key'].encode()
		poloniexUtil.secret_key=os.environ['poloniex_secret_key'].encode()
	else:
		logger.error('please check you exchange access key exist in your environment')
		sys.exit()
def initWallet():
	wallet['okex']=okexUtil.getWallet()
	wallet['poloniex']=poloniexUtil.getWallet()
	logger.info('Finish load wallet:{}'.format(str(wallet)))
async def makeDecision():
	if len(okex_book)>0 and len(poloniex_book)>0:
		ok_ask_head=min(okex_book['ask'],key=lambda subItem:float(subItem))
		ok_ask_head_volume=okex_book['ask'][ok_ask_head]
		ok_ask_head=float(ok_ask_head)
		
		ok_bid_head=max(okex_book['bid'],key=lambda subItem:float(subItem))
		ok_bid_head_volume=okex_book['bid'][ok_bid_head]
		ok_bid_head=float(ok_bid_head)
		logger.debug("okex < ask {}:{} ,bid {}:{}".format(ok_ask_head,ok_ask_head_volume,ok_bid_head,ok_bid_head_volume))
		

		poloniex_ask_head=min(poloniex_book['ask'],key=lambda subItem:float(subItem))
		poloniex_ask_head_volume=poloniex_book['ask'][poloniex_ask_head]
		poloniex_ask_head=float(poloniex_ask_head)

		poloniex_bid_head=max(poloniex_book['bid'],key=lambda subItem:float(subItem))
		poloniex_bid_head_volume=poloniex_book['bid'][poloniex_bid_head]
		poloniex_bid_head=float(poloniex_bid_head)
		logger.debug("poloniex< ask {}:{} ,bid {}:{}".format(poloniex_ask_head,poloniex_ask_head_volume,poloniex_bid_head,poloniex_bid_head_volume))
		
		ok_buy_profit=poloniex_bid_head-ok_ask_head-(poloniex_bid_head*0.0025+ok_ask_head*0.001)
		if ok_buy_profit>0.15:
			logger.debug('over ok_buy threshold')
			min_maket_volume=min(poloniex_bid_head_volume,ok_ask_head_volume)
			min_wallet_volume=min(wallet['okex']['USDT']['free']/ok_ask_head,wallet['poloniex']['ETC']['free'])
			min_volume=min(min_wallet_volume,min_maket_volume)
			if min_volume< 0.00001:
				logger.debug('[trade]no enough volume for trade in ok buy,give up')
			else:
				usd_volume=min_volume*ok_ask_head
				wallet['okex']['USDT']['free']-=usd_volume
				wallet['okex']['USDT']['locked']+=usd_volume
				wallet['poloniex']['ETC']['free']-=min_volume
				wallet['poloniex']['ETC']['locked']+=min_volume
				loop=asyncio.get_event_loop()
				future1 = loop.run_in_executor(None, okexUtil.buy,'etc_usdt',ok_ask_head,min_volume)
				future2 = loop.run_in_executor(None, poloniexUtil.sell,'USDT_ETC',poloniex_bid_head,min_volume)
				response1 = await future1
				response2 = await future2
				logger.info('[trade]Finish trade:{},{}. Wallet status:{}'.format(str(response1),str(response2),str(wallet)))

		poloniex_buy_profit=ok_bid_head-poloniex_ask_head-(poloniex_ask_head*0.0025+ok_bid_head*0.001)
		if poloniex_buy_profit>-0.03:
			min_maket_volume=min(poloniex_ask_head_volume,ok_bid_head_volume)
			min_wallet_volume=min(wallet['okex']['ETC']['free'],wallet['poloniex']['USDT']['free']/poloniex_ask_head)
			min_volume=min(min_wallet_volume,min_maket_volume)
			if min_volume< 0.00001:
				logger.debug('[trade]no enough volume for trade in poloniex buy,give up')
			else:
				usd_volume=min_volume*poloniex_ask_head
				wallet['poloniex']['USDT']['free']-=usd_volume
				wallet['poloniex']['USDT']['locked']+=usd_volume
				wallet['okex']['ETC']['free']-=min_volume
				wallet['okex']['ETC']['locked']+=min_volume
				loop=asyncio.get_event_loop()
				future1 = loop.run_in_executor(None, okexUtil.sell,'etc_usdt',ok_bid_head,min_volume)
				future2 = loop.run_in_executor(None, poloniexUtil.buy,'USDT_ETC',poloniex_ask_head,min_volume)
				response1 = await future1
				response2 = await future2
				logger.info('[trade]Finish trade:{},{}. Wallet status:{}'.format(str(response1),str(response2),str(wallet)))
	else:
		logger.error('some error happen in orderbook monitor')



initAll()
initWallet()
loop=asyncio.get_event_loop()
loop.run_until_complete(handler())
