import sqlite3
import socket
import json
import sys
import bcrypt
from threading import Thread
import os
from datetime import datetime, timedelta
import logging

sys.path.append(".")
from utils import Utils

class UserManager:
    # 单例模式
    _instance = None
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        ''')
        self.conn.commit()
        self.online_users = {}
    
    def _validate_credentials(self, username, password, register = False):
        success, message = Utils.is_valid_username_then_password(username, password)
        if success:
            self.cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = self.cursor.fetchone()
            if user is None:
                if not register:
                    success, message = False, 'USER_NOT_EXIST'
            elif not register:
                stored_password_hash = user[1]
                if not bcrypt.checkpw(password.encode('utf-8'), stored_password_hash.encode('utf-8')):
                    success, message = False, 'WRONG_PASSWORD'
            else:
                success, message = False, 'USER_HAS_EXIST'
        return success, message

    def register_user(self, username, password):
        success, message  = self._validate_credentials(username, password, True)
        message = Utils.sys_msg_to_user_msg(message)
        if success:
            password_hash = Utils.hash_password(password)
            self.cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
            self.conn.commit()
            message = 'User registered successfully'
        return success, message 

    def login_user(self, username, password):
        success, message = self._validate_credentials(username, password)
        message = Utils.sys_msg_to_user_msg(message) 
        if success:
            message = 'Login successful!'
        return success, message

    def delete_account(self, username, password):
        success, message = self._validate_credentials(username, password)
        message = Utils.sys_msg_to_user_msg(message)
        if success:
            self.cursor.execute('DELETE FROM users WHERE username = ?', (username,))
            self.conn.commit()
            message = 'Account deleted successfully'
        return success, message
    
    def close_connection(self):
        self.conn.close()

class Server:
    def __init__(self, host, port, heartbeat_interval = 10, timeout = 30):
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval  # 心跳包发送间隔（秒）
        self.timeout = timeout  # 心跳包超时时间（秒）
        self.user_manager = UserManager()
    
    def handle_client(self, client_socket, client_address):
        last_heartbeat_time = datetime.now()
        username = None
        while True:
            try:
                request = client_socket.recv(1024).decode('utf-8')
            except socket.error:
                logging.info(f"Connection with {client_address} is closed.")
                break
            if request:
                request_data = json.loads(request)
                action = request_data.get('action')
                response = {}
                if action == 'register':
                    response = self.handle_register(request_data)
                elif action == 'login':
                    response = self.handle_login(request_data)
                elif action == 'delete_account':
                    response = self.handle_delete_account(request_data)
                elif action == 'send_message':
                    response = self.handle_send_message(request_data)
                client_socket.send(json.dumps(response).encode('utf-8'))

                if action == 'register' or action == 'delete_account':
                    break
                else:
                    username = request_data.get('username')
                    self.user_manager.online_users[username] = client_socket
                
            else:
                if (datetime.now() - last_heartbeat_time).total_seconds() > self.timeout:
                    logging.info(f"Heartbeat timeout with {client_address}.")
                    break

            # 发送心跳包
            if (datetime.now() - last_heartbeat_time).total_seconds() > self.heartbeat_interval:
                logging.debug(f"Sending heartbeat to {client_address}...")
                client_socket.sendall("heartbeat".encode('utf-8'))
                last_heartbeat_time = datetime.now()
        if username:
            if username in self.user_manager.online_users:
                del self.user_manager.online_users[username]
        client_socket.close()
    
    
    def handle_register(self, request_data):
        username = request_data.get('username')
        password = request_data.get('password')
        success, message = self.user_manager.register_user(username, password)
        return {"success": success, "message": message}

    def handle_login(self, request_data):
        username = request_data.get('username')
        password = request_data.get('password')
        success, message = self.user_manager.login_user(username, password)
        return {"success": success, "message": message}

    def handle_delete_account(self, request_data):
        username = request_data.get('username')
        password = request_data.get('password')
        success, message = self.user_manager.delete_account(username, password)
        return {"success": success, "message": message}

    def handle_send_message(self, request_data):
        content = request_data.get('content')
        sender = request_data.get('username')
        receiver = request_data.get('receiver')
        send_time = request_data.get('send_time')
        success, message = self.send_message(content, sender, receiver, send_time)
        return {"success": success, "message": message}
    
    def send_message(self, content, sender, receiver, send_time):
        if receiver in self.user_manager.online_users:
            receiver_socket = self.user_manager.online_users[receiver]
            message_data = {
                'content': content,
                'sender': sender,
                'send_time': send_time
            }
            message_json = json.dumps(message_data)
            receiver_socket.sendall(message_json.encode('utf-8'))
            return True, 'Message sent successfully'
        else:
            return False, 'Receiver is not online'

    
    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")

        while True:
            client_socket, client_address = server_socket.accept()
            print(f"Client connected from {client_address[0]}:{client_address[1]}")
            client_handler = Thread(target=self.handle_client, args=(client_socket, client_address))
            client_handler.start()

def config_logging(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'):
    logger = logging.getLogger()
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(format)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

if __name__ == '__main__':
    config_logging()
    if os.environ.get('LOCAL') == 'True':
        ip_address = '127.0.0.1'
    else:
        ip_address = '172.31.238.212'
    print(ip_address)
    server = Server(ip_address, 9999)
    server.start()