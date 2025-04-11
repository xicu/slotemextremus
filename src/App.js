import React, { useState, useEffect, useRef } from 'react';
import './styles.css';

function Chrono({ time }) {
  const formatTime = (ms) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    const milliseconds = ms % 1000;
    return `${minutes}:${seconds.toString().padStart(2, '0')}.${milliseconds.toString().padStart(3, '0')}`;
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
  const [history, setHistory] = useState([]); // State to store the history
  const ws = useRef(null);
  const chrono1Ref = useRef(chrono1Time); // Ref to store the latest chrono1Time
  const chrono2Ref = useRef(chrono2Time); // Ref to store the latest chrono2Time

  // Update refs whenever the state changes
  useEffect(() => {
    chrono1Ref.current = chrono1Time;
    chrono2Ref.current = chrono2Time;
  }, [chrono1Time, chrono2Time]);

  useEffect(() => {
    // This socket will work as long as backend and frontend are hosted in the same machine.
    // To host them in different machines, consider mDNS or similar.
    ws.current = new WebSocket(`ws://${window.location.hostname}:8080/ws`);

    ws.current.onmessage = (e) => {
      const message = e.data;
      const now = Date.now();

      if (message === '1') {
        setHistory((prev) => [{ chrono1: chrono1Ref.current, chrono2: null }, ...prev]); // Use ref for chrono1Time
        setStart1(now);
        setChrono1Time(0);
      } else if (message === '2') {
        setHistory((prev) => [{ chrono1: null, chrono2: chrono2Ref.current }, ...prev]); // Use ref for chrono2Time
        setStart2(now);
        setChrono2Time(0);
      }
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, []); // Empty dependency array to ensure WebSocket is initialized only once

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
      <table className="history-table">
        <thead>
          <tr>
            <th>Chrono 1</th>
            <th>Chrono 2</th>
          </tr>
        </thead>
        <tbody>
          {history.map((entry, index) => (
            <tr key={index}>
              <td>{entry.chrono1 !== null ? entry.chrono1 : '-'}</td>
              <td>{entry.chrono2 !== null ? entry.chrono2 : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

