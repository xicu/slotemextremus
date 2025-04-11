package main

import (
	"fmt"
	"log"
	"net/http"
	"sync"

	"github.com/gorilla/mux"
	"github.com/gorilla/websocket"
)

var (
	upgrader = websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
	connections = struct {
		sync.RWMutex
		conns map[*websocket.Conn]bool
	}{conns: make(map[*websocket.Conn]bool)}
)

func main() {
	r := mux.NewRouter()

	// WebSocket endpoint
	r.HandleFunc("/ws", handleWebSocket)

	// POST endpoint
	r.HandleFunc("/lap/{id}", handlePost).Methods("POST")

	log.Println("Server running on :8080")
	log.Fatal(http.ListenAndServe(":8080", r))
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
	// Upgrade to WebSocket
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade failed: %v", err)
		return
	}
	defer conn.Close()

	// Register connection
	connections.Lock()
	connections.conns[conn] = true
	connections.Unlock()
	log.Printf("Client connected: %s", conn.RemoteAddr())

	// Remove connection when closed
	defer func() {
		connections.Lock()
		delete(connections.conns, conn)
		connections.Unlock()
		log.Printf("Client disconnected: %s", conn.RemoteAddr())
	}()

	// Keep connection alive
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			break
		}
	}
}

func handlePost(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	id := vars["id"]

	connections.RLock()
	defer connections.RUnlock()

	// Broadcast to all WebSocket connections
	for conn := range connections.conns {
		if err := conn.WriteMessage(websocket.TextMessage, []byte(id)); err != nil {
			log.Printf("Failed to send to WebSocket: %v", err)
			conn.Close()
		}
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "Broadcasted '%s' to %d clients", id, len(connections.conns))
}
