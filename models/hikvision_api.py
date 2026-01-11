# -*- coding: utf-8 -*-
"""
Hikvision API Request Mixin

Bu mixin Hikvision qurilmalariga HTTP so'rovlar yuborish uchun
asosiy metodlarni o'z ichiga oladi.
"""

import json
import logging

import requests
from requests.auth import HTTPDigestAuth

from odoo import models

# Timeout sozlamalari
DEFAULT_TIMEOUT = 10
MULTIPART_TIMEOUT = 30

_logger = logging.getLogger(__name__)


class HikvisionApiMixin(models.AbstractModel):
    """Hikvision API so'rovlari uchun mixin"""
    
    _name = 'hikvision.api.mixin'
    _description = 'Hikvision API Mixin'

    def _get_isapi_url(self, endpoint):
        """ISAPI endpoint URL'ini yaratish"""
        self.ensure_one()
        return f"http://{self.ip_address}:{self.port}/ISAPI/{endpoint}"

    def _make_request(self, method, endpoint, data=None, params=None):
        """
        Hikvision qurilmasiga HTTP so'rov yuborish.
        
        Args:
            method: 'GET', 'POST', 'PUT'
            endpoint: ISAPI endpoint (masalan: 'System/deviceInfo')
            data: Request body (string yoki dict)
            params: Query parameters
        
        Returns:
            requests.Response object
        
        Raises:
            Exception: Ulanish xatosi bo'lganda
        """
        self.ensure_one()
        
        url = self._get_isapi_url(endpoint)
        auth = HTTPDigestAuth(self.username, self.password)
        
        try:
            if method == 'GET':
                response = requests.get(url, auth=auth, params=params, timeout=DEFAULT_TIMEOUT)
            elif method == 'POST':
                response = requests.post(url, auth=auth, data=data, timeout=DEFAULT_TIMEOUT)
            elif method == 'PUT':
                response = requests.put(url, auth=auth, data=data, timeout=DEFAULT_TIMEOUT)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Connection failed: {str(e)}")
    
    def _make_request_multipart(self, method, endpoint, data=None, content_type=None):
        """
        Multipart so'rovlar uchun maxsus metod (fayllar yuklash uchun).
        
        Args:
            method: HTTP method
            endpoint: ISAPI endpoint
            data: Binary data
            content_type: Content-Type header
        
        Returns:
            requests.Response object
        """
        self.ensure_one()
        
        url = self._get_isapi_url(endpoint)
        auth = HTTPDigestAuth(self.username, self.password)
        
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        
        try:
            response = requests.post(url, auth=auth, data=data, headers=headers, timeout=MULTIPART_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"Upload error: {str(e)}")
    
    def _make_request_multipart_put(self, endpoint, data=None, content_type=None):
        """
        PUT metodi bilan multipart so'rov yuborish (yuz rasmini yangilash uchun).
        
        Hikvision dokumentatsiyasiga ko'ra FDModify endpoint PUT talab qiladi.
        
        Args:
            endpoint: ISAPI endpoint
            data: Binary data
            content_type: Content-Type header
        
        Returns:
            requests.Response object
        """
        self.ensure_one()
        
        url = self._get_isapi_url(endpoint)
        auth = HTTPDigestAuth(self.username, self.password)
        
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        
        try:
            response = requests.put(url, auth=auth, data=data, headers=headers, timeout=MULTIPART_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"Update error: {str(e)}")
