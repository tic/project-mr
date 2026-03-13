from beatman.app import app

if __name__ == '__main__':
  # Background monitoring disabled - using manual download workflow
  # To re-enable automatic playlist monitoring, uncomment the lines below:
  # import threading
  # from beatman.app import monitor_playlists
  # monitor_thread = threading.Thread(target=monitor_playlists, daemon=True)
  # monitor_thread.start()

  # Start Flask app
  app.run(host='0.0.0.0', port=5000, debug=False)
