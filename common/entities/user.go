package entities

import "time"

type User struct {
	ID        string `gorm:"primaryKey"`
	Username  string `gorm:"uniqueIndex"`
	Email     string `gorm:"uniqueIndex"`
	Password  string
	FirstName string
	LastName  string
	DOB       time.Time
	Location  string
	Gender    string
	CreatedAt time.Time
	UpdatedAt time.Time
}
