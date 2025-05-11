package main

import (
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

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
	timeStr := r.FormValue("time") // from the "data" field in Python

	// Save all the images (up to 32MB)
	err := r.ParseMultipartForm(32 << 20)
	if err != nil {
		http.Error(w, "Bad form data", http.StatusBadRequest)
		return
	}
	files := r.MultipartForm.File["image"]
	err = saveUploadedImages(id, files)
	if err != nil {
		http.Error(w, "Failed to save images", http.StatusInternalServerError)
		return
	}

	// Broadcast ID (or include time if you want)
	connections.RLock()
	defer connections.RUnlock()
	for conn := range connections.conns {
		msg := fmt.Sprintf("Car %s crossed at %s", id, timeStr)
		if err := conn.WriteMessage(websocket.TextMessage, []byte(msg)); err != nil {
			log.Printf("WebSocket send error: %v", err)
			conn.Close()
		}
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "Broadcasted '%s' at '%s' to %d clients", id, timeStr, len(connections.conns))
}

func saveUploadedImages(id string, files []*multipart.FileHeader) error {
	// Create a local temp folder like ./tmp/
	baseDir := "tmp"
	err := os.MkdirAll(baseDir, os.ModePerm)
	if err != nil {
		return err
	}

	for _, header := range files {
		file, err := header.Open()
		if err != nil {
			log.Printf("Error opening file: %v", err)
			continue
		}
		defer file.Close()

		// Use timestamp to avoid name collisions
		timestamp := time.Now().Format("20060102_150405.000")
		filename := fmt.Sprintf("%s_%s", timestamp, header.Filename)
		savePath := filepath.Join(baseDir, filename)

		out, err := os.Create(savePath)
		if err != nil {
			log.Printf("Error creating file: %v", err)
			continue
		}
		defer out.Close()

		io.Copy(out, file)
		log.Printf("Saved file to %s", savePath)
	}
	return nil
}
