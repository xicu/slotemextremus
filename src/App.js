import React, { useState, useEffect, useRef } from 'react';
import './styles.css';

function Chrono({ time }) {
  const formatTime = (ms) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    const milliseconds = ms % 1000;
    return `${minutes}:${seconds.toString().padStart(2, '0')}:${milliseconds.toString().padStart(3, '0')}`;
  };

  return (
    <div className="chrono">
      <h2>{formatTime(time)}</h2>
    </div>
  );
}

function App() {
  const [chrono1Time, setChrono1Time] = useState(0);
  const [chrono2Time, setChrono2Time] = useState(0);
  const [start1, setStart1] = useState(null);
  const [start2, setStart2] = useState(null);
  const ws = useRef(null);

  useEffect(() => {
    ws.current = new WebSocket('ws://localhost:8080/ws');

    ws.current.onmessage = (e) => {
      const message = e.data;
      const now = Date.now();

      if (message === '1') {
        setStart1(now);
        setChrono1Time(0);
      } else if (message === '2') {
        setStart2(now);
        setChrono2Time(0);
      }
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, []);

  useInterval(() => {
    if (start1 !== null) {
      const elapsed = Date.now() - start1;
      setChrono1Time(elapsed);
    }
  }, 10);

  useInterval(() => {
    if (start2 !== null) {
      const elapsed = Date.now() - start2;
      setChrono2Time(elapsed);
    }
  }, 10);

  return (
    <div className="App">
      <h1>Slotem Extremus</h1>
      <div className="chrono-container">
        <Chrono time={chrono1Time} />
        <Chrono time={chrono2Time} />
      </div>
    </div>
  );
}

// Custom hook for intervals
function useInterval(callback, delay) {
  const savedCallback = useRef();

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    function tick() {
      savedCallback.current();
    }
    if (delay !== null) {
      let id = setInterval(tick, delay);
      return () => clearInterval(id);
    }
  }, [delay]);
}

export default App;

