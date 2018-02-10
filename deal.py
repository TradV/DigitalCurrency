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
SUPPOR_PAIR='ETC_USDT'
MAX_TRADE_SIZE=3
okexUtil=okexUtil(SUPPOR_PAIR)
poloniexUtil=poloniexUtil(SUPPOR_PAIR)
lock = asyncio.Lock()


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
trade_lock=False
async def trade_handler():
	global trade_lock
	#at a time ,only one trade can be processed
	#at same time, not block other order book update
	if trade_lock:
		logger.debug('TradeLocked ignore the orderbook update')
		return
	ok_head=okexUtil.get_orderbook_head()
	poloniex_head=poloniexUtil.get_orderbook_head()
	if ok_head is not None and poloniex_head is not None:
		(ok_ask_head,ok_ask_head_volume,ok_bid_head,ok_bid_head_volume)=ok_head
		(poloniex_ask_head,poloniex_ask_head_volume,poloniex_bid_head,poloniex_bid_head_volume)=poloniex_head

		
		ok_buy_profit=poloniex_bid_head-ok_ask_head-(poloniex_bid_head*0.0025+ok_ask_head*0.002)
		if ok_buy_profit>0.1:

			min_volume=min([poloniex_bid_head_volume,ok_ask_head_volume,okexUtil.get_buy_avaliable_amount(ok_ask_head),poloniexUtil.get_sell_avaliable_amount(),MAX_TRADE_SIZE])
			if min_volume< 0.01 or min_volume*poloniex_bid_head<1:
				logger.debug('[trade]no enough volume for trade in ok buy,give up:{}'.format(ok_buy_profit))
			else:
				trade_lock=True
				results = await asyncio.gather(okexUtil.buy(ok_ask_head,min_volume),poloniexUtil.sell(poloniex_bid_head,min_volume),)
				logger.info('[trade]Finish okex buy:{!r}. profit:{}'.format(results,ok_buy_profit))
				trade_lock=False

		poloniex_buy_profit=ok_bid_head-poloniex_ask_head-(poloniex_ask_head*0.0025+ok_bid_head*0.002)
		if poloniex_buy_profit>0.01:
			min_volume=min([poloniex_ask_head_volume,ok_bid_head_volume,okexUtil.get_sell_avaliable_amount(),poloniexUtil.get_buy_avaliable_amount(poloniex_ask_head),MAX_TRADE_SIZE])
			if min_volume< 0.01 or min_volume*poloniex_ask_head<1:
				logger.debug('[trade]no enough volume for trade in poloniex buy,give up:{}'.format(poloniex_buy_profit))
			else:
				trade_lock=True
				results = await asyncio.gather(okexUtil.sell(ok_bid_head,min_volume),poloniexUtil.buy(poloniex_ask_head,min_volume),)
				trade_lock=False
				logger.info('[trade]Finish poloniex buy:{!r}. profit:{}'.format(results,poloniex_buy_profit))
		logger.debug('buy_profit:{}|{}|{}|{}'.format(ok_head,poloniex_head,ok_buy_profit,poloniex_buy_profit))

	else:
		logger.error('some error happen in orderbook monitor:{},{}'.format(ok_head,poloniex_head))




async def refreshWallet():
	while True:
		await asyncio.wait([poloniexUtil.init_wallet(),okexUtil.init_wallet()],return_when=asyncio.FIRST_COMPLETED,)
		await asyncio.sleep(300)
async def handle_unfinish_order():
	while True:
		await asyncio.sleep(60)
		await asyncio.wait([poloniexUtil.unfinish_order_handler(),okexUtil.unfinish_order_handler()],return_when=asyncio.FIRST_COMPLETED,)
async def handler():
	return await asyncio.wait([poloniexUtil.order_book(trade_handler),okexUtil.order_book(trade_handler),refreshWallet(),handle_unfinish_order()],return_when=asyncio.FIRST_COMPLETED,)

initAll()
loop=asyncio.get_event_loop()
loop.run_until_complete(handler())
