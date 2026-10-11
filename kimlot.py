import os
import socket
import sys
import threading
import time

# Puertos de red locales
UDP_DISCOVERY_PORT = 5051
TCP_COMM_PORT = 5052
BUF_SIZE = 4096


def print_status(online, error_msg=''):
  """Muestra el indicador de estado en línea / no línea con el formato requerido."""
  if online:
    print('\033[92m[En línea]\033[0m')  # Verde
    print(
        'Su dispositivo está en línea cualquier otro dispositivo puede intentar'
        ' configurarse a su dispositivo'
    )
  else:
    print('\033[91m[No línea]\033[0m')  # Rojo
    print(f'Error: {error_msg}')


def get_local_ip():
  """Obtiene la IP local actual de la máquina en la red Wi-Fi."""
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    # No necesita conectar realmente, solo detecta la ruta de red local
    s.connect(('10.255.255.255', 1))
    ip = s.getsockname()[0]
  except Exception:
    ip = '127.0.0.1'
  finally:
    s.close()
  return ip


def discovery_listener(device_name, stop_event):
  """Escucha peticiones de descubrimiento UDP de otros dispositivos en la red."""
  udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  try:
    udp_sock.bind(('0.0.0.0', UDP_DISCOVERY_PORT))
  except Exception:
    return

  while not stop_event.is_set():
    try:
      udp_sock.settimeout(1.0)
      data, addr = udp_sock.recvfrom(BUF_SIZE)
      if data.startswith(b'KIMLOT_DISCOVER'):
        # Responder con nuestro nombre y IP
        response = f'KIMLOT_HERE:{device_name}'.encode('utf-8')
        udp_sock.sendto(response, addr)
    except socket.timeout:
      continue
    except Exception:
      break
  udp_sock.close()


def search_devices():
  """Busca dispositivos cercanos en la red local mediante UDP Broadcast."""
  print(
      '[*] Buscando dispositivos cercanos en la misma red Wi-Fi (espera 3'
      ' segundos)...'
  )
  udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
  udp_sock.settimeout(3.0)

  devices = []
  message = b'KIMLOT_DISCOVER'

  try:
    # Enviar broadcast a la red local
    udp_sock.sendto(message, ('255.255.255.255', UDP_DISCOVERY_PORT))
  except Exception:
    pass

  start_time = time.time()
  while time.time() - start_time < 3.0:
    try:
      data, addr = udp_sock.recvfrom(BUF_SIZE)
      if data.startswith(b'KIMLOT_HERE'):
        _, dev_name = data.decode('utf-8').split(':', 1)
        device_info = {'ip': addr[0], 'name': dev_name}
        if device_info not in devices and addr[0] != get_local_ip():
          devices.append(device_info)
    except socket.timeout:
      continue
    except Exception:
      break

  udp_sock.close()
  return devices


def chat_session(conn, is_server):
  """Bucle interactivo de chat y transferencia de archivos estilo terminal."""
  print(
      '\n[+] ¡Conexión establecida con éxito! Ya puedes chatear o enviar'
      ' archivos.'
  )
  print('    - Escribe tu mensaje y presiona Enter para enviar texto.')
  print('    - Escribe /file <ruta_del_archivo> para enviar un archivo.')
  print('    - Escribe /exit para cerrar la conexión.\n')

  def receive_loop():
    while True:
      try:
        header = conn.recv(1024).decode('utf-8')
        if not header:
          print('\n[-] El otro dispositivo cerró la conexión.')
          break

        if header == 'TEXT':
          msg_len = int(conn.recv(1024).decode('utf-8'))
          text_data = conn.recv(msg_len).decode('utf-8')
          print(f'\n[Compañero]: {text_data}\nTú > ', end='', flush=True)

        elif header == 'FILE':
          filename = conn.recv(1024).decode('utf-8')
          file_size = int(conn.recv(1024).decode('utf-8'))
          print(
              f'\n[*] Recibiendo archivo entrante: {filename} ({file_size}'
              ' bytes)...'
          )

          received = 0
          with open(filename, 'wb') as f:
            while received < file_size:
              chunk = conn.recv(min(BUF_SIZE, file_size - received))
              if not chunk:
                break
              f.write(chunk)
              received += len(chunk)
          print(
              f'[+] Archivo guardado localmente como: {filename}\nTú > ',
              end='',
              flush=True,
          )
      except Exception:
        break

  threading.Thread(target=receive_loop, daemon=True).start()

  while True:
    try:
      user_input = input('Tú > ')
      if not user_input.strip():
        continue

      if user_input.strip() == '/exit':
        conn.close()
        break

      if user_input.startswith('/file '):
        file_path = user_input.split(' ', 1)[1].strip()
        if not os.path.exists(file_path):
          print(f'[-] El archivo "{file_path}" no existe.')
          continue

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        conn.send('FILE'.encode('utf-8'))
        conn.send(filename.encode('utf-8'))
        conn.send(str(file_size).encode('utf-8'))

        print(f'[*] Enviando archivo {filename}...')
        with open(file_path, 'rb') as f:
          while True:
            chunk = f.read(BUF_SIZE)
            if not chunk:
              break
            conn.send(chunk)
        print('[+] ¡Archivo enviado con éxito!')
      else:
        conn.send('TEXT'.encode('utf-8'))
        encoded_text = user_input.encode('utf-8')
        conn.send(str(len(encoded_text)).encode('utf-8'))
        conn.send(encoded_text)
    except Exception as e:
        print(f'[-] Error al enviar datos: {e}')
        break


def run_server(device_name):
  """Inicia el nodo como receptor, esperando conexiones de emparejamiento."""
  stop_event = threading.Event()
  # Iniciar hilo secundario para responder a escaneos UDP
  t = threading.Thread(
      target=discovery_listener, args=(device_name, stop_event), daemon=True
  )
  t.start()

  server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

  try:
    server.bind(('0.0.0.0', TCP_COMM_PORT))
    server.listen(1)
    print_status(True)
    print(f'[*] Tu IP local: {get_local_ip()}')
    print('[*] Esperando solicitudes de acoplamiento de otros dispositivos...\n')

    conn, addr = server.accept()
    print(f'[+] Solicitud de conexión entrante desde el dispositivo: {addr[0]}')

    # Recibir nombre del dispositivo remoto que quiere acoplarse
    remote_name = conn.recv(1024).decode('utf-8')
    decision = input(
        f'[?] ¿Deseas aceptar el acoplamiento con "{remote_name}"? (s/n): '
    ).strip().lower()

    if decision == 's':
      conn.send(b'ACCEPT')
      print('[+] Acoplamiento aceptado.')
      stop_event.set()
      server.close()
      chat_session(conn, is_server=True)
    else:
      conn.send(b'REJECT')
      print('[-] Acoplamiento rechazado.')
      conn.close()
      server.close()

  except Exception as e:
    print_status(False, str(e))


def main():
  device_name = socket.gethostname()

  if len(sys.argv) > 1 and sys.argv[1] == 'start':
    run_server(device_name)
    return

  print('=== KIMLOT LOCAL SHARE CLI ===')
  print(f'Tu dispositivo actual se identifica como: {device_name}')
  print('1. Iniciar modo escucha / servidor')
  print('2. Buscar dispositivos cercanos y conectar')
  opcion = input('\nSelecciona una opción (1 o 2): ').strip()

  if opcion == '1':
    run_server(device_name)
  elif opcion == '2':
    devices = search_devices()
    if not devices:
      print('[-] No se encontró ningún dispositivo activo en la red.')
      return

    print('\n[+] Dispositivos encontrados:')
    for i, dev in enumerate(devices):
      print(f'  [{i}] {dev["name"]} ({dev["ip"]})')

    choice = input(
        '\nElige el número del dispositivo al que deseas conectarte: '
    ).strip()
    try:
      idx = int(choice)
      target = devices[idx]
    except (ValueError, IndexError):
      print('[-] Selección inválida.')
      return

    print(f'[*] Conectando a {target["name"]} ({target["ip"]})...')
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      client.connect((target['ip'], TCP_COMM_PORT))
      # Enviar nuestro nombre para el emparejamiento
      client.send(device_name.encode('utf-8'))

      print('[*] Esperando que el otro dispositivo acepte el acoplamiento...')
      response = client.recv(1024)

      if response == b'ACCEPT':
        print('[+] ¡El otro dispositivo aceptó la conexión!')
        chat_session(client, is_server=False)
      else:
        print('[-] El otro dispositivo rechazó la conexión.')
        client.close()
    except Exception as e:
        print(f'[-] No se pudo conectar al dispositivo: {e}')
  else:
    print('[-] Opción no válida.')


if __name__ == '__main__':
  main()
