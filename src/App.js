import { useState, useEffect } from 'react';

export default function MisHuevos() {
  const [message, setMessage] = useState(''); // State to store WebSocket messages

  useEffect(() => {
    const socket = new WebSocket('ws://localhost:8080/ws'); // Replace with your WebSocket URL

    socket.onmessage = (event) => {
      console.log('WebSocket message received:', event.data); // Print the message to the console
      setMessage(event.data); // Update message state when a new message is received
      //setMessage(Date().toISOString())
    };

    return () => {
      socket.close(); // Clean up WebSocket connection on component unmount
    };
  }, []);

  return (
    <div className="mierdas">
        <div className="websocket-message">Message: {message}</div> {/* Display WebSocket message */}
    </div>
  );
}
