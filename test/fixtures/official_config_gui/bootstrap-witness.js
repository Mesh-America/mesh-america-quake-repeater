const connect = async() => {
      app.connecting = true;
      try {
        await cli.connect();
        await cli.setTime((Date.now() / 1000) | 0);
        showMessage('Time sync: OK');
        await getData();
        app.connected = true;
        app.locked = false;
      }
      catch(err) {
        alert(`Cannot connect: ${err.message}`);
      }
      finally {
        app.connecting = false;
      }
      await getPresets();
      console.log(app);
    };
const disconnect = async() => {
      await cli.disconnect();
      app.connecting = app.connected = false;
      app.locked = true;
    };
