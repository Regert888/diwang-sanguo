# -*- coding: utf-8 -*-
"""
军情查询模块
操作码: 5166 reqCountryMilitary
"""

import struct
import time


def 查询军情(client):
    """
    查询国家军情（出征、警报、驻军等信息）

    Returns:
        dict: {
            'expeditions': [],  # 出征列表
            'alerts': [],       # 警报列表
            'garrison': []      # 驻军列表
        }
    """
    # 5166 reqCountryMilitary 请求包通常只需要一个空包或简单标记
    payload = struct.pack(">B", 0)  # 单字节标记

    packets = client.send_ops([(5166, payload)])

    if not packets:
        return {'expeditions': [], 'alerts': [], 'garrison': []}

    # 查找响应包 (5166 + 0x7000 = 0x342E = 13358)
    resp_op = 5166 + 0x7000
    for pkt in packets:
        if pkt.get("op") == resp_op:
            return 解析军情响应(pkt.get("data", b""))

    return {'expeditions': [], 'alerts': [], 'garrison': []}


def 解析军情响应(data):
    """
    解析军情响应包

    协议格式待测试，先返回原始数据用于调试
    """
    if not data or len(data) < 4:
        return {'expeditions': [], 'alerts': [], 'garrison': [], 'raw': data.hex()}

    result = {
        'expeditions': [],  # 出征中的部队
        'alerts': [],       # 警报信息
        'garrison': [],     # 驻军信息
        'raw_hex': data.hex(),
        'raw_len': len(data)
    }

    # 尝试解析基础结构
    try:
        offset = 0
        # 通常会有计数字段
        if len(data) >= 4:
            count = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4
            result['count'] = count

        # 暂时保存原始数据，等实际调用后再完善解析逻辑
        result['raw_data'] = list(data[:min(100, len(data))])

    except Exception as e:
        result['parse_error'] = str(e)

    return result

