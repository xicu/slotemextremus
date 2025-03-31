package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/gorilla/websocket"
)

type User struct {
	ID       string `json:"id"`
	Username string `json:"username"`
	Email    string `json:"email"`
}

var users []User
var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for simplicity
	},
}

func main() {
	http.HandleFunc("/", handler)
	http.HandleFunc("GET /users/{id}", getUsers)
	http.HandleFunc("POST /users/{id}", createUser)
	http.HandleFunc("/socket", socketHandler) // WebSocket endpoint
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func handler(w http.ResponseWriter, r *http.Request) {
	fmt.Fprint(w, "Hello, World!")
	log.Default().Println("Hello, World!")
}

func getUsers(w http.ResponseWriter, r *http.Request) {
	fmt.Fprint(w, "getUsers")
	//json.NewEncoder(w).Encode(users)
}

func createUser(w http.ResponseWriter, r *http.Request) {
	fmt.Fprint(w, "createUser")
	var newUser User
	_ = json.NewDecoder(r.Body).Decode(&newUser)
	users = append(users, newUser)
	json.NewEncoder(w).Encode(newUser)
}

func socketHandler(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Println("Upgrade error:", err)
		return
	}
	defer conn.Close()
	fmt.Fprint(w, "El socket del server haciendo movidas")

	for {
		timestamp := time.Now().Format(time.RFC3339)
		err := conn.WriteMessage(websocket.TextMessage, []byte(timestamp))
		if err != nil {
			log.Println("Write error:", err)
			break
		}
		time.Sleep(1 * time.Second)
	}
}
