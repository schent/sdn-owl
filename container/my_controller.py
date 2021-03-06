#!/bin/python3
# Copyright (C) 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from operator import attrgetter
from influxdb import InfluxDBClient
from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from pprint import pprint
import time
import json
import array


class SimpleMonitor13(simple_switch_13.SimpleSwitch13):

    def __init__(self, *args, **kwargs):
        super(SimpleMonitor13, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(3)

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):

        body = ev.msg.body
        self.logger.debug('Receive Message : ' +
                          time.strftime("%Y-%m-%d %H:%M:%S"))
        self.logger.debug('datapath         '
                          'in-port  eth-dst           '
                          'out-port packets  bytes')
        self.logger.debug('---------------- '
                          '-------- ----------------- '
                          '-------- -------- --------')
        for stat in sorted([flow for flow in body if flow.priority == 1],
                           key=lambda flow: (flow.match['in_port'],
                                             flow.match['eth_dst'])):
            self.logger.debug('%016x %8x %17s %8x %8d %8d',
                              ev.msg.datapath.id,
                              stat.match['in_port'], stat.match['eth_dst'],
                              stat.instructions[0].actions[0].port,
                              stat.packet_count, stat.byte_count)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        for stat in ev.msg.body:
            portStat_data = [
                {
                    "measurement": "testbed",
                    "fields": {
                        "port_no": stat.port_no,
                        "rx_pkts": stat.rx_packets,
                        "tx_pkts": stat.tx_packets,
                        "rx_bytes": stat.rx_bytes,
                        "tx_bytes": stat.tx_bytes,
                        "rx_dropped": stat.rx_dropped,
                        "tx_dropped": stat.tx_dropped,
                        "rx_errors": stat.rx_errors,
                        "tx_errors": stat.tx_errors,
                        "rx_frame_err": stat.rx_frame_err,
                        "rx_over_err": stat.rx_over_err,
                        "collisions": stat.collisions,
                        "duration_sec": stat.duration_sec,
                        "duration_nsec": stat.duration_nsec
                    }
                }
            ]

        portStat_data[0]["fields"]['switch_ip'] = str(
            ev.msg.datapath.address[0])
        self._addToInfluxDB(portStat_data)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    def _addToInfluxDB(self, sendPortStat_data, host='db', port=8086):
        # pprint(sendPortStat_data)
        user = 'owl'
        password = 'sdnowl'
        dbname = 'mydb'
        client = InfluxDBClient(host, port, user, password, dbname)
        client.create_database(dbname)
        client.write_points(sendPortStat_data)
        print "Adding data to influxDB"
