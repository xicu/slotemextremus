package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type User struct {
	ID       string `json:"id"`
	Username string `json:"username"`
	Email    string `json:"email"`
}

var users []User

func main() {
	http.HandleFunc("/", handler)
	http.HandleFunc("GET /users/{id}", getUsers)
	http.HandleFunc("POST /users/{id}", createUser)
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func handler(w http.ResponseWriter, r *http.Request) {
	fmt.Fprint(w, "Hello, World!")
	log.Default().Println("Request received")
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
