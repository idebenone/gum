package entities

type Action struct {
	ID          string `gorm:"primaryKey"`
	UserID      string
	Description string
	CreatedAt   int64
}
