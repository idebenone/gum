package entities

import (
	"time"
)

type Observation struct {
	ID           int64          `gorm:"primaryKey;autoIncrement"`
	ObserverName string         `gorm:"size:100;not null"`
	UserID       int64          `gorm:"not null;index"`
	Content      string         `gorm:"type:text;not null"`
	ContentType  string         `gorm:"size:50;not null"`
	CreatedAt    time.Time      `gorm:"autoCreateTime"`
	UpdatedAt    time.Time      `gorm:"autoUpdateTime"`
	Propositions []*Proposition `gorm:"many2many:observation_proposition;constraint:OnDelete:CASCADE;"`
}
